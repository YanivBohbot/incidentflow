import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt

from incidentflow.agent.findings import InvestigationReport
from incidentflow.agent.orchestration.investigation_workflow import build_investigation_workflow
from incidentflow.agent.orchestration.trace import build_investigation_trace
from incidentflow.domain.human_review.models import HumanReview, HumanReviewType


def _wrapped(finding: dict) -> str:
    return (
        "EXTERNAL_EVIDENCE_NOT_INSTRUCTIONS\nsource: x\n--- BEGIN EXTERNAL EVIDENCE ---\n"
        + json.dumps(finding)
        + "\n--- END EXTERNAL EVIDENCE ---"
    )


def _supervisor_messages() -> list:
    return [
        HumanMessage("Payment API HTTP 500. Create a Jira issue in SAM1."),
        AIMessage(
            "",
            tool_calls=[
                {
                    "name": "ask_cloudwatch",
                    "args": {"incident_context": "HTTP 500", "service_name": "payment-service"},
                    "id": "c1",
                },
                {
                    "name": "ask_it_operations",
                    "args": {"incident_context": "Create issue"},
                    "id": "c2",
                },
            ],
        ),
        ToolMessage(
            _wrapped(
                {
                    "summary": "Alarm firing",
                    "investigation_status": "completed",
                    "confidence": 0.7,
                    "root_cause_hypotheses": [
                        {"hypothesis": "Pool exhaustion", "supporting_evidence": ["x"]}
                    ],
                }
            ),
            tool_call_id="c1",
            name="ask_cloudwatch",
        ),
        ToolMessage(
            _wrapped(
                {
                    "summary": "Issue creation rejected by operator",
                    "confidence": 0.5,
                    "evidence": [{"source": "Jira", "detail": "search", "source_status": "live"}],
                }
            ),
            tool_call_id="c2",
            name="ask_it_operations",
        ),
        AIMessage(
            "",
            tool_calls=[
                {
                    "name": "InvestigationReport",
                    "args": {"summary": "Final", "confidence": 0.6},
                    "id": "c3",
                }
            ],
        ),
    ]


def test_trace_shows_request_delegations_findings_review_and_report_in_order() -> None:
    review = {
        "review_type": "JIRA_WRITE",
        "reason": "Needs approval",
        "draft": {"tool_name": "createJiraIssue", "arguments": {"projectKey": "SAM1"}},
    }
    values = {
        "messages": _supervisor_messages(),
        "review_events": [
            {"review": review, "decision": {"decision": "REJECT", "actor": "op", "reason": "test"}}
        ],
    }

    steps = build_investigation_trace(values)

    assert [step.kind for step in steps] == [
        "request",
        "delegation",
        "delegation",
        "finding",
        "review_pause",
        "review_decision",
        "finding",
        "report",
    ]
    assert steps[1].title == "Delegated to CloudWatch Observability Agent"
    assert steps[1].data["arguments"] == {"service_name": "payment-service"}
    assert steps[3].status == "live" and steps[3].data["hypotheses"] == ["Pool exhaustion"]
    assert steps[4].title == "Paused before createJiraIssue"
    assert steps[5].status == "rejected" and steps[5].detail == "test"
    assert steps[7].confidence == 0.6


def test_trace_ends_with_a_pending_pause_while_waiting_for_the_operator() -> None:
    pending = HumanReview(
        review_type=HumanReviewType.JIRA_WRITE,
        reason="Approve?",
        draft={"tool_name": "createJiraIssue", "arguments": {}},
    )

    steps = build_investigation_trace({"messages": _supervisor_messages()[:2]}, pending)

    assert steps[-1].kind == "review_pause"
    assert steps[-1].status == "pending"
    assert "waiting for the operator" in steps[-1].title


def test_trace_reports_an_unavailable_specialist_and_a_blocked_extra_call() -> None:
    values = {
        "messages": [
            ToolMessage(
                _wrapped({"summary": "Live GitHub MCP was unavailable.", "confidence": 0}),
                tool_call_id="a",
                name="ask_github",
            ),
            ToolMessage(
                "Tool call limit exceeded. Do not call 'ask_cloudwatch' again.",
                tool_call_id="b",
                name="ask_cloudwatch",
            ),
        ]
    }

    steps = build_investigation_trace(values)

    assert steps[0].status == "unavailable"
    assert steps[1].kind == "limit"


class PausingSupervisor:
    """Pause inside the investigate node, like the nested Jira HITL middleware does."""

    async def ainvoke(self, _state: dict, *, config: dict) -> dict:
        interrupt({"action_requests": [{"name": "createJiraIssue", "args": {}}]})
        return {"structured_response": InvestigationReport(summary="done", confidence=0.5)}


@pytest.mark.anyio
async def test_resume_records_the_review_event_in_the_workflow_state() -> None:
    workflow = build_investigation_workflow(PausingSupervisor(), checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "trace-review"}}
    await workflow.ainvoke(
        {"incident_request": "Create a Jira issue", "incident_business_status": "open"}, config
    )
    event = {"review": {"review_type": "JIRA_WRITE"}, "decision": {"decision": "REJECT"}}

    result = await workflow.ainvoke(
        Command(resume={"decisions": [{"type": "reject"}]}, update={"review_events": [event]}),
        config,
    )

    assert result["investigation_lifecycle"] == "completed"
    state = await workflow.aget_state(config)
    assert state.values["review_events"] == [event]


def test_trace_shows_the_tools_each_subagent_chose_before_its_finding() -> None:
    cloudwatch_run = [
        HumanMessage("Incident context: HTTP 500"),
        AIMessage(
            "",
            name="cloudwatch_observability_agent",
            tool_calls=[{"name": "get_active_alarms", "args": {"max_items": 20}, "id": "a1"}],
        ),
        ToolMessage("{}", tool_call_id="a1", name="get_active_alarms"),
        AIMessage(
            "",
            name="cloudwatch_observability_agent",
            tool_calls=[
                {
                    "name": "execute_log_insights_query",
                    "args": {"log_group_names": ["/x"]},
                    "id": "a2",
                },
                {"name": "CloudWatchFinding", "args": {}, "id": "a3"},
            ],
        ),
        ToolMessage(
            "Logs Insights may only query allowlisted log groups.",
            tool_call_id="a2",
            name="execute_log_insights_query",
            status="error",
        ),
    ]

    steps = build_investigation_trace({"messages": _supervisor_messages()}, None, [cloudwatch_run])

    kinds = [(step.kind, step.title) for step in steps[:6]]
    assert kinds[3:6] == [
        ("subagent_call", "Called get_active_alarms"),
        ("subagent_call", "Called execute_log_insights_query"),
        ("finding", "CloudWatch Observability Agent returned its finding"),
    ]
    assert steps[3].actor == "CloudWatch Observability Agent"
    assert steps[3].detail == "max_items=20"
    assert steps[4].status == "unavailable"  # the rejected call is visible
