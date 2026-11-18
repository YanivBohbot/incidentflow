# LangSmith Evaluation — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure the real supervisor's trajectory/tool usage and the real workflow's report
quality as reproducible LangSmith experiments, with a generated summary table.

**Architecture:** The production supervisor builder gains an optional `tools=` seam; evals pass
fixture delegations that copy the real tools' metadata, record calls, and return frozen
findings. A trajectory recorder captures delegations, nested tool calls, graph nodes, and
interrupts into run outputs. Stdlib code evaluators are uploaded to each dataset with the
`langsmith` CLI (auto-run); LLM judges run locally in `aevaluate`.

**Tech Stack:** Python 3.12/3.13, LangChain `create_agent`, LangGraph, `langsmith` SDK
(`aevaluate`, `Client`), `langsmith` CLI 0.5.0, `agentevals` (local trajectory judge),
`langchain-openai`, pytest + anyio.

**Spec:** `docs/superpowers/specs/2026-11-18-langsmith-evaluation-design.md` (phase 1 only;
phases 2 and 3 get their own plans).

## Global Constraints

- All paths below are relative to `apps/api` unless they start with `docs/`.
- **Everything evaluation-related lives in `apps/api/evaluation/`** (owner's requirement), a
  package run from `apps/api` with `python -m evaluation.<module>`. Layout: `run.py`,
  `upload_evaluators.py`, `summary.py`, `retrieval.py`, `README.md`, and sub-packages
  `scenarios/`, `evaluators/`, `harness/`, `tests/`. The only change under `src/` is the
  supervisor `tools=` seam (Task 2). Production code never imports `evaluation`.
- Ruff 100-char lines, type annotations, `test_<behavior>` names; commits end with the
  `Co-Authored-By:` trailer. Work on branch `feature/langsmith-evaluation`.
- Evaluations never write to real Jira, GitHub, MongoDB, or Pinecone.
- Default mode uses frozen fixtures; `--live-integrations` uses the real `ask_*` tools.
- `aevaluate(..., num_repetitions=3)` by default (`--repetitions N` overrides).
- Judge model: new setting `eval_judge_model: str = "gpt-4.1"` (`EVAL_JUDGE_MODEL`), separate
  from `openai_model`; both recorded in experiment metadata with `prompt_hash`.
- Code evaluators: stdlib only, imports inside the function body, accept `run`/`example` as
  object or dict, return exactly `{"score": int|float, "comment": str}`, self-contained (no
  module-level helpers — the CLI uploads one function). Uploaded evaluators are **not** also
  passed to `aevaluate`.
- Datasets: `incidentflow-supervisor-trajectory` (new), `incidentflow-investigation-reports`
  (existing, 3 examples, synced in place). Scenario name = `metadata.scenario` = sync key.
- Per-tool delegation limit = 2 (matches `ToolCallLimitMiddleware`).
- Never run the `langsmith` CLI with `--yes`.

## Review Focus

1. Supervisor ends without a structured report (`report` is `None`, lifecycle `failed`) → every
   report evaluator scores 0 with a comment instead of raising. *(Task 4 test)*
2. The run function raises (model error, timeout) → `outputs` is empty; every code evaluator
   returns score 0 with "no outputs", never a `KeyError`. *(Task 4 test)*
3. Two examples run concurrently (`--max-concurrency 2`) → each run gets its own recorder and
   fixture tools; calls never leak between runs. *(Task 7 test)*
4. A scenario is edited and the sync re-run → only that example is updated, nothing is
   duplicated, the 3 pre-existing examples are updated in place by scenario name. *(Task 5 test)*
5. The supervisor calls a specialist with no frozen finding in the scenario → the stub returns
   the same zero-confidence "unavailable" finding shape production uses, and the call is still
   recorded. *(Task 2 test)*

---

### Task 1: Evaluation folder, eval dependencies, and trajectory-capture spike

**Files:**
- Modify: `pyproject.toml` — add `eval = ["agentevals>=0.0.9,<0.1", "openevals>=0.2.5,<0.3"]`
  under `[project.optional-dependencies]`; `[tool.pytest.ini_options]` becomes
  `testpaths = ["tests", "evaluation/tests"]` and `pythonpath = ["."]`
- Modify: `.github/workflows/ci.yml` and `CLAUDE.md` — API lint step becomes
  `ruff check src tests scripts evaluation`
- Move (`git mv`): `src/incidentflow/agent/evaluation/investigation_reports.py` and
  `supervisor_routing.py` → `evaluation/scenarios/`; `scripts/evaluate_investigation_reports.py`
  → `evaluation/legacy_reports.py` and `scripts/evaluate_supervisor_routing.py` →
  `evaluation/legacy_routing.py` (both kept runnable until Task 9 deletes them); `scripts/evaluate_knowledge_retrieval.py` → `evaluation/retrieval.py`;
  `tests/test_investigation_report_evaluation.py`, `tests/test_supervisor_routing_evaluation.py`
  → `evaluation/tests/`. Delete the now-empty `src/incidentflow/agent/evaluation/`.
  (`incidentflow.knowledge.evaluation` and its test stay in `src/` until phase 3.)
- Create: `__init__.py` in `evaluation/` and each sub-package; `evaluation/README.md` (layout +
  one line per command, filled in as tasks land)
- Create: `evaluation/spike_trajectory_capture.py` (throwaway, deleted in Task 9)
- Create: `docs/superpowers/notes/2026-11-18-trajectory-capture-spike.md`

- [ ] **Step 1:** `git checkout -b feature/langsmith-evaluation`; commit the spec and this plan.
- [ ] **Step 2:** Add the `eval` extra; run `pip install -e ".[dev,eval]"`. Expected: installs.
- [ ] **Step 3:** Do the moves, fix imports (`from evaluation.scenarios.investigation_reports
  import ...`), update pytest/ruff/CI config. Run `pytest -q` and `ruff check src tests scripts
  evaluation`. Expected: same test count as before the move, all pass. Commit
  `Move evaluation code into a dedicated evaluation folder`.
- [ ] **Step 4:** Write the spike: run `build_investigation_workflow(build_investigation_supervisor(),
  checkpointer=InMemorySaver())` on scenario `EVAL-PAY-001` with live integrations disabled and
  `LANGSMITH_TRACING=true`, three ways in one run: (a) a `BaseCallbackHandler` passed in
  `config["callbacks"]` recording `on_tool_start` (name, inputs, `parent_run_id`); (b)
  `astream(..., stream_mode="updates")` recording node names; (c) after the run, reading child
  runs of the root trace with `Client().list_runs(trace_id=..., run_type="tool")`.
- [ ] **Step 5:** Run it. Record in the notes file, for each method: whether it sees the
  supervisor's `ask_*` calls, the Knowledge specialist's nested Pinecone tool call, the node
  path, and the `__interrupt__` value. Expected: (a) sees nested calls because
  `subagent_config` keeps parent callbacks — confirm or refute.
- [ ] **Step 6:** Write the decision in the notes (expected: callback handler for tools +
  `stream_mode="updates"` for nodes). If (a) misses nested calls, stop and bring the finding
  back to the owner before Task 3. Commit.

### Task 2: Supervisor seam and fixture delegations

**Files:**
- Modify: `src/incidentflow/agent/orchestration/supervisor.py` (`build_investigation_supervisor`)
- Create: `evaluation/harness/fixtures.py`
- Test: `evaluation/tests/test_fixtures.py`

**Interfaces:**
- Produces: `build_investigation_supervisor(tools: list[BaseTool] | None = None)` — `None`
  keeps the five real tools.
- Produces: `DELEGATION_TOOLS: tuple[BaseTool, ...]` (the five real `ask_*` tools, in
  `supervisor.py`, used as the default).
- Produces: `CallLog = list[dict[str, Any]]` entries `{"tool": str, "args": dict}`.
- Produces: `fixture_delegations(findings: Mapping[str, str], call_log: CallLog) -> list[BaseTool]`
  — one stub per real tool, same `name`, `description`, `args_schema`; returns
  `findings[name]` or the placeholder.
- Produces: `unavailable_finding_json(tool_name: str) -> str` — zero-confidence finding of the
  right model with summary `"<source> is unavailable in this evaluation scenario."`.

- [ ] **Step 1: Write failing tests**

```python
def test_fixture_delegations_copy_real_tool_metadata() -> None:
    stubs = {t.name: t for t in fixture_delegations({}, [])}
    for real in DELEGATION_TOOLS:
        assert stubs[real.name].description == real.description
        assert stubs[real.name].args == real.args

@pytest.mark.anyio
async def test_fixture_delegation_returns_frozen_finding_and_records_call() -> None:
    log: CallLog = []
    stub = {t.name: t for t in fixture_delegations({"ask_knowledge": '{"x": 1}'}, log)}
    assert await stub["ask_knowledge"].ainvoke({"incident_context": "pool"}) == '{"x": 1}'
    assert log == [{"tool": "ask_knowledge", "args": {"incident_context": "pool"}}]

@pytest.mark.anyio
async def test_fixture_delegation_without_finding_returns_unavailable_placeholder() -> None:
    log: CallLog = []
    stub = {t.name: t for t in fixture_delegations({}, log)}
    finding = json.loads(await stub["ask_github"].ainvoke({"incident_context": "c"}))
    assert finding["confidence"] == 0 and "unavailable" in finding["summary"]
    assert log[0]["tool"] == "ask_github"

def test_build_investigation_supervisor_accepts_injected_tools(monkeypatch) -> None:
    # set OPENAI_API_KEY via monkeypatch + get_settings.cache_clear()
    agent = build_investigation_supervisor(tools=fixture_delegations({}, []))
    assert agent is not None
```

- [ ] **Step 2:** `pytest evaluation/tests/test_fixtures.py -v` → FAIL (import error).
- [ ] **Step 3:** Implement. Stubs via `StructuredTool.from_function(coroutine=..., name=real.name,
  description=real.description, args_schema=real.args_schema)`; the finding model per tool
  comes from a `{tool_name: FindingModel}` map in `fixtures.py`. Pass `tools` through to
  `create_agent`; middleware tool names stay unchanged.
- [ ] **Step 4:** Run the new tests and `pytest -q` → all PASS.
- [ ] **Step 5:** Commit `Add a tools seam to the supervisor and fixture delegations`.

### Task 3: Trajectory recorder

**Files:**
- Create: `evaluation/harness/trajectory.py`
- Test: `evaluation/tests/test_trajectory.py`

**Interfaces:**
- Consumes: decision from Task 1 notes.
- Produces: `class TrajectoryRecorder(AsyncCallbackHandler)` with `nested_tool_calls:
  list[dict]` (`{"agent": str | None, "tool": str, "args": dict}`, excluding the five `ask_*`
  names) and `def as_outputs(self) -> dict[str, Any]`.
- Produces: `async def run_workflow_recorded(workflow, incident_request: str, call_log: CallLog)
  -> dict[str, Any]` returning the run-output contract: `report` (JSON or `None`),
  `delegations` (= `call_log`), `nested_tool_calls`, `graph_path: list[str]`,
  `interrupts: list[{"kind": str, "tool": str | None}]`, `lifecycle`, `errors`. Uses a fresh
  `thread_id` `evaluation:<uuid4>`, `astream(stream_mode="updates")` for nodes, and scores at an
  interrupt (no resume). `kind` is `"report_review"` for the `review` node interrupt and
  `"jira_write"` when the interrupt value has `action_requests`.

- [ ] **Step 1: Failing tests** — with a tiny fake `StateGraph` (nodes `a → b`) whose node calls a
  `@tool` named `searchJiraIssuesUsingJql` with the recorder in config:
  `test_recorder_captures_nested_tool_calls_and_skips_delegations`,
  `test_run_workflow_recorded_returns_graph_path_in_order` (`graph_path == ["a", "b"]`),
  `test_run_workflow_recorded_records_report_review_interrupt_without_resuming` (node calls
  `interrupt({...})`; asserts `interrupts == [{"kind": "report_review", "tool": None}]` and
  `report` taken from state).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement per the Task 1 decision.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `Record evaluation trajectories from workflow runs`.

### Task 4: Code evaluators

**Files:**
- Create: `evaluation/evaluators/code.py`
- Modify: `evaluation/scenarios/investigation_reports.py` (keep its helpers; the
  report script stops using them in Task 7)
- Test: `evaluation/tests/test_code_evaluators.py`

**Interfaces:**
- Produces (each `(run, example) -> {"score", "comment"}`, self-contained):
  - trajectory dataset: `required_specialists_called`, `forbidden_specialists_not_called`,
    `delegation_calls_within_limit` (≤ 2 per tool), `delegation_args_contain_key_facts`
    (case-insensitive: every `example.outputs["key_facts"]` string appears in the concatenated
    `args.incident_context` of the delegations; score = fraction found).
  - reports dataset: `graph_path_valid` (path starts `validate, prepare, investigate,
    capture_report` and ends `finalize`, or ends `review` with a `report_review` interrupt),
    `report_has_required_fields` (`summary`, `agents_consulted`, `evidence`, `confidence` in
    [0, 1]), `evidence_attributed`, `evidence_from_delegated_sources` (every
    `evidence.source` maps to a delegated tool via `example.outputs["source_tools"]`, a
    `{source_name: tool_name}` map), `no_live_evidence_from_unavailable`.
- Produces: `TRAJECTORY_CODE_EVALUATORS` and `REPORT_CODE_EVALUATORS` — tuples of function names
  (used by Task 8's upload script).

- [ ] **Step 1: Failing tests** — for each evaluator a pass case and a fail case built from plain
  dicts and from `SimpleNamespace(outputs=...)`, plus:

```python
@pytest.mark.parametrize("evaluator", ALL_CODE_EVALUATORS)
def test_code_evaluator_scores_zero_when_run_has_no_outputs(evaluator) -> None:
    result = evaluator({"outputs": None}, {"outputs": FULL_REFERENCE})
    assert result["score"] == 0 and result["comment"]

@pytest.mark.parametrize("evaluator", REPORT_EVALUATOR_FUNCS)
def test_report_evaluator_scores_zero_when_report_is_missing(evaluator) -> None:
    run = {"outputs": {"report": None, "lifecycle": "failed", "graph_path": ["validate", "fail"]}}
    assert evaluator(run, {"outputs": FULL_REFERENCE})["score"] == 0

def test_code_evaluators_import_only_the_standard_library() -> None:
    # parse evaluation/evaluators/code.py with ast; every Import/ImportFrom module is in sys.stdlib_module_names
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `Add stdlib code evaluators for trajectory and reports`.

### Task 5: Scenario catalog with frozen findings, and idempotent dataset sync

**Files:**
- Create: `evaluation/scenarios/catalog.py`
- Create: `evaluation/harness/dataset_sync.py`
- Modify: `evaluation/scenarios/supervisor_routing.py` (scenarios move to
  `scenarios.py`; keep `assess_delegations`)
- Test: `evaluation/tests/test_scenarios.py`, `evaluation/tests/test_dataset_sync.py`; update
  `evaluation/tests/test_supervisor_routing_evaluation.py` imports.

**Interfaces:**
- Produces: `@dataclass(frozen=True) class EvaluationScenario`: `name`, `incident_request`,
  `frozen_findings: Mapping[str, str]` (tool → finding JSON), `required_specialists`,
  `forbidden_specialists: frozenset[str]`, `key_facts: tuple[str, ...]`,
  `expected_root_cause: str | None`, `unsafe_actions: tuple[str, ...]`,
  `source_tools: Mapping[str, str]`.
- Produces: `TRAJECTORY_SCENARIOS` (≥ 8: the 6 existing routing scenarios with findings added,
  plus `cloudwatch_and_github_deploy_regression` and `no_specialist_needed_greeting` with
  `required_specialists=frozenset()`), `REPORT_SCENARIOS` (≥ 8: `EVAL-PAY-001`,
  `EVAL-AUTH-002`, `EVAL-CODE-003` unchanged names, plus ≥ 5 new covering the seeded services
  and one "insufficient evidence" case).
- Produces: `def trajectory_example(s) -> ExampleSpec`, `def report_example(s) -> ExampleSpec`,
  `ExampleSpec = dict` with `inputs`, `outputs`, `metadata={"scenario": name}`.
- Produces: `def sync_dataset(client, name: str, description: str, examples: list[ExampleSpec])
  -> SyncResult` (`created`, `updated`, `unchanged` counts); when anything changed, tags the new
  version `"v<UTC yyyymmddHHMM>"` via `client.update_dataset_tag`.

- [ ] **Step 1: Failing tests** — `test_frozen_findings_validate_against_their_finding_models`
  (each JSON parses into the model from Task 2's map), `test_scenario_names_are_unique`,
  `test_report_scenarios_keep_the_three_existing_names`, and with a fake client (in-memory
  examples, records `create_examples`/`update_example`/`update_dataset_tag`):
  `test_sync_creates_missing_examples`, `test_sync_updates_changed_example_by_scenario_name`
  (pre-seeded with the old `EVAL-PAY-001` shape → `updated == 1`, total count unchanged),
  `test_sync_second_run_is_a_noop_and_does_not_tag`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement; frozen findings are realistic, cite
  correlation IDs, and contain the key facts. **Step 4:** Run → PASS (+ full `pytest -q`).
- [ ] **Step 5:** Commit `Add evaluation scenarios with frozen findings and dataset sync`.

### Task 6: LLM judges

**Files:**
- Modify: `src/incidentflow/core/config.py` (`eval_judge_model`), `apps/api/.env.example`
- Create: `evaluation/evaluators/judges.py`
- Test: `evaluation/tests/test_judges.py`

**Interfaces:**
- Produces: `def build_judges(model: BaseChatModel) -> list[Callable]` returning async
  evaluators `root_cause_identified`, `report_grounded_in_findings` (judge sees the scenario's
  frozen findings and the report; fails on any fact absent from findings), `safe_remediation`
  (unsafe actions from reference), and `investigation_path_reasonable` (wraps
  `agentevals.trajectory.llm.create_async_trajectory_llm_as_judge` over the recorded
  delegations rendered as OpenAI-style tool-call messages). Each scores 0 with a comment when
  `report` is `None`.
- Produces: `def prompt_hash() -> str` — first 12 hex chars of sha256 over
  `SUPERVISOR_SYSTEM_PROMPT + TOOL_SELECTION_SYSTEM_PROMPT`.

- [ ] **Step 1: Failing tests** — fake chat model returning fixed structured grades:
  `test_judge_scores_one_when_grade_passes`, `test_judges_score_zero_without_report`,
  `test_eval_judge_model_defaults_to_gpt_4_1_and_reads_env`, `test_prompt_hash_changes_with_prompt`
  (monkeypatch the prompt constant).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (structured output `method="json_schema",
  strict=True`, temperature 0). **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `Add LLM judges with a separately pinned model`.

### Task 7: `evaluation/run.py` for the trajectory and reports suites

**Files:**
- Create: `evaluation/harness/runner.py` (testable core)
- Create: `evaluation/run.py` (argparse wrapper)
- Test: `evaluation/tests/test_runner.py`

**Interfaces:**
- Consumes: Tasks 2–6.
- Produces: `def make_run_function(suite: Literal["trajectory", "reports"], *, live: bool)
  -> Callable[[dict], Awaitable[dict]]` — per call: new `CallLog`, `fixture_delegations`
  (or real tools when `live`), new supervisor + workflow with `InMemorySaver`, then
  `run_workflow_recorded`. Scenario lookup by `inputs["scenario"]` (inputs carry
  `incident_request` and `scenario`).
- Produces: `async def run_suite(suite, *, live: bool, repetitions: int, max_concurrency: int,
  client: Client) -> str` — syncs the dataset, calls `aevaluate` with `evaluators` = judges only,
  `num_repetitions`, `experiment_prefix=f"{suite}"`, metadata `{model, judge_model,
  prompt_hash, live_integrations, suite}`; returns the experiment name.
- CLI: `python -m evaluation.run --suite trajectory|reports|all [--live-integrations]
  [--repetitions 3] [--max-concurrency 1]`. Live mode keeps the existing flag behaviour
  (integration flags forced false unless `--live-integrations`).

- [ ] **Step 1: Failing tests** — `test_run_function_isolates_call_logs_between_concurrent_runs`
  (two `asyncio.gather` calls with a fake supervisor factory; each output's `delegations`
  contains only its own call), `test_run_suite_passes_only_judges_and_repetitions` (fake
  `aevaluate` captures kwargs: `num_repetitions == 3`, no code evaluator in `evaluators`,
  metadata keys present).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement; inject `aevaluate` and the supervisor factory
  as parameters for tests. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `Add a single evaluation entry point for trajectory and reports`.

### Task 8: Evaluator upload and summary table

**Files:**
- Create: `evaluation/upload_evaluators.py`
- Create: `evaluation/harness/report_table.py`, `evaluation/summary.py`
- Test: `evaluation/tests/test_summary.py`

**Interfaces:**
- Consumes: `TRAJECTORY_CODE_EVALUATORS`, `REPORT_CODE_EVALUATORS` (Task 4).
- Produces: `python -m evaluation.upload_evaluators [--dry-run]` — for each (dataset, function) runs
  `langsmith evaluator upload evaluation/evaluators/code.py --name
  <function> --function <function> --dataset <dataset> --replace` (CLI path from
  `LANGSMITH_CLI` env, else `langsmith` on PATH, else
  `%LOCALAPPDATA%\Programs\langsmith\bin\langsmith.exe`); `--dry-run` prints the commands.
  Never passes `--yes`.
- Produces: `@dataclass ExperimentScores(dataset: str, name: str, url: str, scores: dict[str,
  float])`, `def render_summary(latest: list[ExperimentScores], previous: dict[str,
  ExperimentScores]) -> str` (Markdown: one table per dataset, columns Metric | Latest |
  Previous | Δ, plus experiment links and a "How to run" section), and
  `def fetch_experiment_scores(client, dataset: str) -> tuple[ExperimentScores |
  None, ExperimentScores | None]` (latest two projects by `start_time` for the dataset, mean
  feedback per key).
- `evaluation/summary.py` writes `docs/evaluation.md`.

- [ ] **Step 1: Failing tests** — `test_render_summary_shows_delta_against_previous`
  (0.67 → 1.00 renders `+0.33`), `test_render_summary_marks_missing_previous_as_dash`,
  `test_upload_dry_run_lists_every_evaluator_once` (capsys; count == len of both tuples, no
  `--yes`).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `Upload code evaluators and render the evaluation summary`.

### Task 9: Retire old scripts, run real experiments, publish the table

**Files:**
- Delete: `evaluation/spike_trajectory_capture.py`, `evaluation/legacy_reports.py`,
  `evaluation/legacy_routing.py` (all superseded by `python -m evaluation.run`)
- Modify: `evaluation/README.md` (final layout, every command, what each dataset measures)
- Modify: `CLAUDE.md` (Commands and Tests sections: `pip install -e ".[dev,eval]"`, the
  `evaluation/` folder,, `python -m evaluation.run`,
  `python evaluation/upload_evaluators.py`, `python evaluation/summary.py`)
- Create (generated): `docs/evaluation.md`

- [ ] **Step 1:** `ruff check src tests scripts evaluation` and `ruff format --check src tests evaluation` → clean;
  `pytest -q` → all pass (report the count).
- [ ] **Step 2:** `python -m evaluation.run --suite all --repetitions 1` once (sync + smoke).
  Expected: two experiments listed in LangSmith; inspect one trace of each and confirm
  `delegations`, `nested_tool_calls`, `graph_path` are populated as expected.
- [ ] **Step 3:** `python evaluation/upload_evaluators.py --dry-run`, then without `--dry-run`
  (owner confirms CLI prompts). Expected: `langsmith evaluator list` shows every evaluator on
  its dataset.
- [ ] **Step 4:** `python -m evaluation.run --suite all` (3 repetitions). Expected: code
  evaluator columns auto-populate, judge columns populate, no duplicate columns.
- [ ] **Step 5:** `python evaluation/summary.py`; review `docs/evaluation.md` with the
  owner. Commit `Run phase 1 evaluations and publish the summary`.
