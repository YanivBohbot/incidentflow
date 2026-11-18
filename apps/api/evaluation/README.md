# Evaluation

LangSmith evaluation tooling for IncidentFlow. Run everything from `apps/api` with
`python -m evaluation.<module>` after `pip install -e ".[dev,eval]"`. Production code under `src/`
never imports this package.

## Layout

- `scenarios/` - scenario definitions and code evaluators (investigation reports, routing)
- `tests/` - offline tests for the evaluation code (collected by `pytest`)
- `legacy_reports.py`, `legacy_routing.py` - old experiment scripts, removed once replaced
- `retrieval.py` - knowledge retrieval evaluation
- `spike_trajectory_capture.py` - throwaway trajectory-capture spike

## Commands

- `python -m evaluation.legacy_reports` - investigation-report experiment (legacy)
- `python -m evaluation.legacy_routing` - supervisor routing experiment (legacy)
- `python -m evaluation.retrieval` - knowledge retrieval evaluation
- `python -m evaluation.spike_trajectory_capture` - trajectory-capture spike (throwaway)
