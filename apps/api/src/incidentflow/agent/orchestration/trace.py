"""Rebuild a readable timeline of one investigation from its LangGraph checkpoint.

The supervisor is a create_agent loop, so its checkpointed messages already tell the story:
the operator request, each delegation (tool call) with the context the supervisor chose, each
specialist finding (tool result), and the final structured report. Human reviews are added
from the workflow's review_events and from a review that is still pending.
"""

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from incidentflow.agent.guardrails.external_evidence import unwrap_external_evidence
from incidentflow.agent.identities import (
    CLOUDWATCH_OBSERVABILITY_AGENT,
    DATA_INTELLIGENCE_AGENT,
    GITHUB_AGENT,
    INVESTIGATION_SUPERVISOR,
    IT_OPERATIONS_AGENT,
    KNOWLEDGE_AGENT,
)
from incidentflow.domain.human_review.models import HumanReview
from incidentflow.domain.investigations.models import InvestigationTraceStep

SPECIALIST_BY_TOOL = {
    "ask_it_operations": IT_OPERATIONS_AGENT,
    "ask_data_intelligence": DATA_INTELLIGENCE_AGENT,
    "ask_knowledge": KNOWLEDGE_AGENT,
    "ask_github": GITHUB_AGENT,
    "ask_cloudwatch": CLOUDWATCH_OBSERVABILITY_AGENT,
}
AGENT_BY_TECHNICAL_NAME = {
    identity.technical_name: identity for identity in SPECIALIST_BY_TOOL.values()
}
REPORT_TOOL = "InvestigationReport"
SUPERVISOR = INVESTIGATION_SUPERVISOR.display_name


def _specialist_name(tool_name: str) -> str:
    identity = SPECIALIST_BY_TOOL.get(tool_name)
    return identity.display_name if identity else tool_name


def _finding_payload(content: Any) -> dict[str, Any] | None:
    """Return the specialist finding JSON, without the external-evidence wrapper."""
    text = unwrap_external_evidence(content if isinstance(content, str) else json.dumps(content))
    try:
        payload = json.loads(text.strip())
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _finding_status(payload: dict[str, Any]) -> str:
    statuses = {item.get("source_status") for item in payload.get("evidence", []) or []}
    summary = str(payload.get("summary", "")).casefold()
    if "unavailable" in summary or payload.get("investigation_status") == "unavailable":
        return "unavailable"
    if "live" in statuses or payload.get("investigation_status") in {"completed", "partial"}:
        return "live"
    return "unavailable" if not payload.get("confidence") else "info"


def _finding_step(message: ToolMessage) -> InvestigationTraceStep:
    actor = _specialist_name(message.name or "")
    content = str(message.content)
    if content.startswith("Tool call limit exceeded"):
        return InvestigationTraceStep(
            kind="limit",
            actor="Call limit middleware",
            title=f"Blocked an extra call to {actor}",
            detail=content,
            status="info",
        )
    payload = _finding_payload(message.content)
    if payload is None:
        return InvestigationTraceStep(
            kind="finding", actor=actor, title=f"{actor} answered", detail=content[:2000]
        )
    evidence = payload.get("evidence", []) or []
    return InvestigationTraceStep(
        kind="finding",
        actor=actor,
        title=f"{actor} returned its finding",
        detail=str(payload.get("summary", "")),
        status=_finding_status(payload),  # type: ignore[arg-type]
        confidence=payload.get("confidence"),
        data={
            "evidence": [
                {
                    "source": item.get("source"),
                    "status": item.get("source_status"),
                    "detail": item.get("detail"),
                }
                for item in evidence
                if isinstance(item, dict)
            ],
            "hypotheses": payload.get("hypotheses")
            or payload.get("suspected_root_causes")
            or [item.get("hypothesis") for item in payload.get("root_cause_hypotheses", [])],
            "limitations": payload.get("limitations", []) or payload.get("errors", []),
        },
    )


def _review_pause_step(review: dict[str, Any], *, pending: bool) -> InvestigationTraceStep:
    draft = review.get("draft") or {}
    tool_name = draft.get("tool_name")
    is_jira = review.get("review_type") == "JIRA_WRITE"
    return InvestigationTraceStep(
        kind="review_pause",
        actor="Human-in-the-loop middleware" if is_jira else "Review policy",
        title=(
            f"Paused before {tool_name} — waiting for the operator"
            if is_jira and pending
            else f"Paused before {tool_name}"
            if is_jira
            else "Paused for an operator review"
        ),
        detail=str(review.get("reason", "")),
        status="pending" if pending else "info",
        data={
            "review_type": review.get("review_type"),
            "tool_name": tool_name,
            "arguments": draft.get("arguments", {}),
        },
    )


def _review_decision_step(decision: dict[str, Any]) -> InvestigationTraceStep:
    kind = str(decision.get("decision", ""))
    edited = decision.get("edited_draft") or {}
    title = {
        "APPROVE": "Operator approved" + (" with edits" if edited else ""),
        "REJECT": "Operator rejected",
        "REQUEST_INFORMATION": "Operator requested more information",
    }.get(kind, "Operator decided")
    return InvestigationTraceStep(
        kind="review_decision",
        actor=f"Operator ({decision.get('actor', 'unknown')})",
        title=title,
        detail=str(decision.get("reason") or ""),
        status="approved" if kind == "APPROVE" else "rejected",
        data={"edited_fields": edited},
    )


def _brief(arguments: dict[str, Any]) -> str:
    """One-line summary of tool arguments for the timeline."""
    parts = []
    for name, value in arguments.items():
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        parts.append(f"{name}={text[:120]}")
    return ", ".join(parts)


def _subagent_call_steps(messages: list[Any]) -> list[InvestigationTraceStep]:
    """The tools one specialist agent chose inside its own create_agent loop."""
    results = {
        message.tool_call_id: message for message in messages if isinstance(message, ToolMessage)
    }
    steps = []
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        identity = AGENT_BY_TECHNICAL_NAME.get(message.name or "")
        actor = identity.display_name if identity else (message.name or "Specialist agent")
        for call in message.tool_calls:
            if call["name"].endswith("Finding"):
                continue  # the structured-output tool, shown as the finding itself
            result = results.get(call["id"])
            failed = result is not None and result.status == "error"
            steps.append(
                InvestigationTraceStep(
                    kind="subagent_call",
                    actor=actor,
                    title=f"Called {call['name']}",
                    detail=_brief(call.get("args", {})),
                    status="unavailable" if failed else "info",
                    data={"result": unwrap_external_evidence(result.content)[:600]}
                    if failed and result is not None
                    else {},
                )
            )
    return steps


def build_investigation_trace(
    values: dict[str, Any],
    pending_review: HumanReview | None = None,
    subagent_runs: list[list[Any]] | None = None,
) -> list[InvestigationTraceStep]:
    """Turn checkpointed workflow values into an ordered, operator-readable timeline.

    subagent_runs holds the messages of each specialist create_agent run, oldest first. Each
    run's tool calls are shown just before that specialist's finding.
    """
    runs_by_agent: dict[str, list[list[Any]]] = {}
    for run in subagent_runs or []:
        agent_name = next((m.name for m in run if isinstance(m, AIMessage) and m.name), None)
        if agent_name:
            runs_by_agent.setdefault(agent_name, []).append(run)
    steps: list[InvestigationTraceStep] = []
    jira_reviews: list[InvestigationTraceStep] = []
    other_reviews: list[InvestigationTraceStep] = []
    for event in values.get("review_events", []) or []:
        review, decision = event.get("review") or {}, event.get("decision") or {}
        target = jira_reviews if review.get("review_type") == "JIRA_WRITE" else other_reviews
        target += [_review_pause_step(review, pending=False), _review_decision_step(decision)]

    for message in values.get("messages", []) or []:
        if isinstance(message, HumanMessage):
            steps.append(
                InvestigationTraceStep(
                    kind="request",
                    actor="Operator",
                    title="Incident request",
                    detail=str(message.content),
                )
            )
        elif isinstance(message, AIMessage):
            if isinstance(message.content, str) and message.content.strip():
                steps.append(
                    InvestigationTraceStep(
                        kind="reasoning",
                        actor=SUPERVISOR,
                        title="Supervisor note",
                        detail=message.content,
                    )
                )
            for call in message.tool_calls:
                if call["name"] == REPORT_TOOL:
                    args = call.get("args", {})
                    steps.append(
                        InvestigationTraceStep(
                            kind="report",
                            actor=SUPERVISOR,
                            title="Supervisor wrote the investigation report",
                            detail=str(args.get("summary", "")),
                            confidence=args.get("confidence"),
                            data={"agents_consulted": args.get("agents_consulted", [])},
                        )
                    )
                    continue
                args = dict(call.get("args", {}))
                steps.append(
                    InvestigationTraceStep(
                        kind="delegation",
                        actor=SUPERVISOR,
                        title=f"Delegated to {_specialist_name(call['name'])}",
                        detail=str(args.pop("incident_context", "")),
                        data={"tool": call["name"], "arguments": args},
                    )
                )
        elif isinstance(message, ToolMessage) and message.name in SPECIALIST_BY_TOOL:
            agent_runs = runs_by_agent.get(SPECIALIST_BY_TOOL[message.name].technical_name)
            if agent_runs:
                steps += _subagent_call_steps(agent_runs.pop(0))
            if message.name == "ask_it_operations" and jira_reviews:
                steps += jira_reviews  # the Jira write paused inside this delegation
                jira_reviews = []
            steps.append(_finding_step(message))

    # A specialist still running or paused (no finding yet): show what it has done so far.
    for agent_runs in runs_by_agent.values():
        for run in agent_runs:
            steps += _subagent_call_steps(run)
    # ToolStrategy may retry the structured report after a validation error: show the last one.
    report_positions = [index for index, step in enumerate(steps) if step.kind == "report"]
    for index in reversed(report_positions[:-1]):
        del steps[index]
    steps += jira_reviews + other_reviews
    if pending_review is not None:
        steps.append(_review_pause_step(pending_review.model_dump(mode="json"), pending=True))
    return steps
