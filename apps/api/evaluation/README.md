# Evaluation

LangSmith evaluation tooling for IncidentFlow. Run everything from `apps/api` with
`python -m evaluation.<module>` after `pip install -e ".[dev,eval]"`. Production code under `src/`
never imports this package. These commands call real OpenAI and LangSmith and are not part of
`pytest`; only `evaluation/tests/` (offline) is collected by `pytest`.

## Layout

- `run.py` - single entry point: syncs datasets, runs experiments, applies judges
- `upload_evaluators.py` - uploads the code evaluators to the LangSmith datasets
- `summary.py` - writes `docs/evaluation.md` from the latest experiments
- `retrieval.py` - knowledge retrieval evaluation (Pinecone)
- `scenarios/` - scenario definitions and the catalog that turns them into dataset examples
- `harness/` - dataset sync, fixtures, trajectory recorder, experiment runner, summary table
- `evaluators/code.py` - code evaluators (uploaded to LangSmith); `evaluators/judges.py` - LLM judges
- `tests/` - offline tests for the evaluation code

## Commands

- `python -m evaluation.run --suite trajectory|reports|all [--live-integrations]
  [--repetitions N] [--max-concurrency N]` - sync datasets and run experiments
  (defaults: 3 repetitions, concurrency 1)
- `python -m evaluation.upload_evaluators [--dry-run]` - upload code evaluators to the datasets
- `python -m evaluation.summary` - write `docs/evaluation.md`
- `python -m evaluation.retrieval` - knowledge retrieval evaluation

## Datasets

- `incidentflow-supervisor-trajectory` (8 scenarios) - does the supervisor consult the right
  specialists for an incident request?
- `incidentflow-investigation-reports` (9 scenarios) - given frozen specialist findings, does the
  report reach the known root cause, stay grounded, and propose safe actions?

## Evaluators

Code evaluators run in LangSmith (uploaded to the datasets, so they populate automatically):

- `required_specialists_called` - every required specialist was delegated to
- `forbidden_specialists_not_called` - no specialist that must be skipped was called
- `delegation_calls_within_limit` - no specialist is called more often than allowed
- `delegation_args_contain_key_facts` - delegation requests carry the incident's key facts
- `graph_path_valid` - the workflow graph path matches the expected lifecycle
- `report_has_required_fields` - the structured report is complete
- `evidence_attributed` - report evidence is present and every item names its source
- `evidence_from_delegated_sources` - evidence only cites specialists that were consulted
- `no_live_evidence_from_unavailable` - disabled integrations are never cited as live evidence

LLM judges run locally inside `evaluation.run` (model `EVAL_JUDGE_MODEL`, default `gpt-4.1`):

- `investigation_path_reasonable` - the sequence of delegations makes sense for the incident
- `root_cause_identified` - the report identifies the expected root cause as primary
- `report_grounded_in_findings` - every claim is supported by the findings or the request
- `safe_remediation` - proposed actions are relevant and avoid known unsafe steps

## Modes

- Fixture mode (default) - specialist delegations return frozen, deterministic findings; no real
  Jira, GitHub, MongoDB, or Pinecone call is made and nothing is written.
- `--live-integrations` - specialists run against the integrations as configured in `.env`; the
  recorder captures the top-level delegations instead.

Each experiment uses `num_repetitions=3` by default to expose run-to-run variance.
