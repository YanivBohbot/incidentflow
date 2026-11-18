"""Code evaluators for LangSmith trajectory and report datasets.

Each function is uploaded on its own (``langsmith evaluator upload``) and runs in a sandbox with
only the standard library, so every function is self-contained: no module-level helpers or
constants are used inside a body, and ``run``/``example`` may be dicts or objects.
"""

TRAJECTORY_CODE_EVALUATORS = (
    "required_specialists_called",
    "forbidden_specialists_not_called",
    "delegation_calls_within_limit",
    "delegation_args_contain_key_facts",
)
REPORT_CODE_EVALUATORS = (
    "graph_path_valid",
    "report_has_required_fields",
    "evidence_attributed",
    "evidence_from_delegated_sources",
    "no_live_evidence_from_unavailable",
    "evidence_status_matches_findings",
)


def required_specialists_called(run, example):
    """Every required specialist was actually delegated to."""
    outputs = run.get("outputs") if isinstance(run, dict) else getattr(run, "outputs", None)
    reference = (
        example.get("outputs") if isinstance(example, dict) else getattr(example, "outputs", None)
    ) or {}
    if not outputs:
        return {"score": 0, "comment": "no outputs"}
    called = {d.get("tool") for d in outputs.get("delegations") or []}
    required = list(reference.get("required_specialists") or [])
    missing = [name for name in required if name not in called]
    return {"score": 0 if missing else 1, "comment": f"missing={missing}"}


def forbidden_specialists_not_called(run, example):
    """No forbidden specialist was delegated to."""
    outputs = run.get("outputs") if isinstance(run, dict) else getattr(run, "outputs", None)
    reference = (
        example.get("outputs") if isinstance(example, dict) else getattr(example, "outputs", None)
    ) or {}
    if not outputs:
        return {"score": 0, "comment": "no outputs"}
    called = {d.get("tool") for d in outputs.get("delegations") or []}
    forbidden = list(reference.get("forbidden_specialists") or [])
    hit = [name for name in forbidden if name in called]
    return {"score": 0 if hit else 1, "comment": f"called_forbidden={hit}"}


def delegation_calls_within_limit(run, example):
    """No specialist tool was delegated to more than twice."""
    outputs = run.get("outputs") if isinstance(run, dict) else getattr(run, "outputs", None)
    if not outputs:
        return {"score": 0, "comment": "no outputs"}
    counts = {}
    for delegation in outputs.get("delegations") or []:
        tool = delegation.get("tool")
        counts[tool] = counts.get(tool, 0) + 1
    over = {tool: n for tool, n in counts.items() if n > 2}
    return {"score": 0 if over else 1, "comment": f"over_limit={over}"}


def delegation_args_contain_key_facts(run, example):
    """Fraction of key facts present in delegation incident_context."""
    outputs = run.get("outputs") if isinstance(run, dict) else getattr(run, "outputs", None)
    reference = (
        example.get("outputs") if isinstance(example, dict) else getattr(example, "outputs", None)
    ) or {}
    if not outputs:
        return {"score": 0, "comment": "no outputs"}
    facts = list(reference.get("key_facts") or [])
    if not facts:
        return {"score": 1, "comment": "no key facts"}
    text = " ".join(
        str((d.get("args") or {}).get("incident_context") or "")
        for d in outputs.get("delegations") or []
    ).lower()
    missing = [fact for fact in facts if str(fact).lower() not in text]
    found = len(facts) - len(missing)
    return {"score": found / len(facts), "comment": f"missing={missing}"}


def graph_path_valid(run, example):
    """The workflow took the expected path and finished or paused for review."""
    outputs = run.get("outputs") if isinstance(run, dict) else getattr(run, "outputs", None)
    if not outputs:
        return {"score": 0, "comment": "no outputs"}
    report = outputs.get("report")
    if not report:
        return {"score": 0, "comment": "no report"}
    path = list(outputs.get("graph_path") or [])
    prefix = ["validate", "prepare", "investigate", "capture_report"]
    if path[:4] != prefix:
        return {"score": 0, "comment": f"bad path={path}"}
    if path[-1] == "finalize":
        return {"score": 1, "comment": "ok"}
    if path[-1] == "review":
        kinds = [i.get("kind") for i in outputs.get("interrupts") or []]
        if "report_review" in kinds:
            return {"score": 1, "comment": "ok (paused for review)"}
        return {"score": 0, "comment": f"review without report_review interrupt={kinds}"}
    return {"score": 0, "comment": f"bad path end={path}"}


def report_has_required_fields(run, example):
    """Report carries summary, agents_consulted, evidence, confidence."""
    outputs = run.get("outputs") if isinstance(run, dict) else getattr(run, "outputs", None)
    if not outputs:
        return {"score": 0, "comment": "no outputs"}
    report = outputs.get("report")
    if not report:
        return {"score": 0, "comment": "no report"}
    missing = [key for key in ("summary", "agents_consulted", "evidence") if not report.get(key)]
    confidence = report.get("confidence")
    valid = (
        isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and 0 <= confidence <= 1
    )
    if not valid:
        missing.append("confidence(0-1)")
    return {"score": 0 if missing else 1, "comment": f"missing={missing}"}


def evidence_attributed(run, example):
    """Every evidence item names its source and carries detail text."""
    outputs = run.get("outputs") if isinstance(run, dict) else getattr(run, "outputs", None)
    if not outputs:
        return {"score": 0, "comment": "no outputs"}
    report = outputs.get("report")
    if not report:
        return {"score": 0, "comment": "no report"}
    items = report.get("evidence") or []
    bad = [
        index
        for index, item in enumerate(items)
        if item.get("source_status") != "unavailable"
        and not (str(item.get("source") or "").strip() and str(item.get("detail") or "").strip())
    ]
    if not items:
        return {"score": 0, "comment": "no evidence"}
    return {"score": 0 if bad else 1, "comment": f"unattributed={bad}"}


def evidence_from_delegated_sources(run, example):
    """Each available evidence source maps to a delegated tool."""
    outputs = run.get("outputs") if isinstance(run, dict) else getattr(run, "outputs", None)
    reference = (
        example.get("outputs") if isinstance(example, dict) else getattr(example, "outputs", None)
    ) or {}
    if not outputs:
        return {"score": 0, "comment": "no outputs"}
    report = outputs.get("report")
    if not report:
        return {"score": 0, "comment": "no report"}
    called = {d.get("tool") for d in outputs.get("delegations") or []}
    source_tools = reference.get("source_tools") or {}
    unmapped = []
    undelegated = []
    for item in report.get("evidence") or []:
        if item.get("source_status") == "unavailable":
            continue
        source = item.get("source")
        # Exact name first, then the longest known alias contained in a descriptive name
        # ("MongoDB operational events" -> "MongoDB").
        tool = source_tools.get(source)
        if tool is None:
            text = str(source or "").lower()
            matches = [key for key in source_tools if key and str(key).lower() in text]
            if matches:
                tool = source_tools[max(matches, key=len)]
        if tool is None:
            unmapped.append(source)
        elif tool not in called:
            undelegated.append(source)
    bad = unmapped + undelegated
    return {
        "score": 0 if bad else 1,
        "comment": f"unmapped={unmapped} undelegated={undelegated}",
    }


def no_live_evidence_from_unavailable(run, example):
    """No live evidence comes from a source that was unavailable."""
    outputs = run.get("outputs") if isinstance(run, dict) else getattr(run, "outputs", None)
    reference = (
        example.get("outputs") if isinstance(example, dict) else getattr(example, "outputs", None)
    ) or {}
    if not outputs:
        return {"score": 0, "comment": "no outputs"}
    report = outputs.get("report")
    if not report:
        return {"score": 0, "comment": "no report"}
    source_tools = reference.get("source_tools") or {}
    unavailable = set(reference.get("unavailable_sources") or [])
    bad = []
    for item in report.get("evidence") or []:
        if item.get("source_status") != "live":
            continue
        source = item.get("source")
        tool = source_tools.get(source)
        if tool is None:
            text = str(source or "").lower()
            matches = [key for key in source_tools if key and str(key).lower() in text]
            tool = source_tools[max(matches, key=len)] if matches else source
        if tool in unavailable:
            bad.append(source)
    return {"score": 0 if bad else 1, "comment": f"live_from_unavailable={bad}"}


def evidence_status_matches_findings(run, example):
    """Live evidence must come from a finding that itself reported live evidence."""
    import json

    outputs = run.get("outputs") if isinstance(run, dict) else getattr(run, "outputs", None)
    reference = (
        example.get("outputs") if isinstance(example, dict) else getattr(example, "outputs", None)
    ) or {}
    if not outputs:
        return {"score": 0, "comment": "no outputs"}
    report = outputs.get("report")
    if not report:
        return {"score": 0, "comment": "no report"}
    source_tools = reference.get("source_tools") or {}
    statuses = {}
    for tool, raw in (reference.get("frozen_findings") or {}).items():
        try:
            finding = json.loads(raw)
        except (TypeError, ValueError):
            continue
        declared = {item.get("source_status") for item in finding.get("evidence") or []}
        declared.discard(None)
        # A finding that declares no status (e.g. CloudWatchFinding) cannot be checked.
        if declared:
            statuses[tool] = declared
    upgraded = []
    for item in report.get("evidence") or []:
        if item.get("source_status") != "live":
            continue
        source = item.get("source")
        tool = source_tools.get(source)
        if tool is None:
            text = str(source or "").lower()
            matches = [key for key in source_tools if key and str(key).lower() in text]
            tool = source_tools[max(matches, key=len)] if matches else None
        if tool in statuses and "live" not in statuses[tool]:
            upgraded.append(source)
    return {"score": 0 if upgraded else 1, "comment": f"relabelled_live={upgraded}"}
