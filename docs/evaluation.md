# Evaluation summary

## incidentflow-supervisor-trajectory

Latest experiment: [trajectory-4ef701b1](https://smith.langchain.com/o/c920c557-3266-4d89-b818-f7e709fe4965/projects/p/229fad0b-c2a9-46ca-97c8-eb58fbb096f1)
Previous experiment: [trajectory-307e2905](https://smith.langchain.com/o/c920c557-3266-4d89-b818-f7e709fe4965/projects/p/45003e35-00ae-426e-b038-f572abe3c525)
Run settings: model: gpt-4.1-mini, judge_model: gpt-4.1, prompt_hash: 127cb5e718c0

| Metric | Latest | Previous | Δ |
| --- | --- | --- | --- |
| delegation_args_contain_key_facts | 1.00 | 1.00 | +0.00 |
| delegation_calls_within_limit | 1.00 | 1.00 | +0.00 |
| forbidden_specialists_not_called | 1.00 | 1.00 | +0.00 |
| investigation_path_reasonable | 0.88 | 0.88 | +0.00 |
| required_specialists_called | 1.00 | 1.00 | +0.00 |

## incidentflow-investigation-reports

Latest experiment: [reports-a888848c](https://smith.langchain.com/o/c920c557-3266-4d89-b818-f7e709fe4965/projects/p/99480a8a-403f-45ca-bb1c-cbe9b1dea812)
Previous experiment: [reports-3be721cc](https://smith.langchain.com/o/c920c557-3266-4d89-b818-f7e709fe4965/projects/p/c4ca63d2-3505-47ac-a138-1a3aef154817)
Run settings: model: gpt-4.1-mini, judge_model: gpt-4.1, prompt_hash: 7de94696dac1

| Metric | Latest | Previous | Δ |
| --- | --- | --- | --- |
| evidence_attributed | 1.00 | 1.00 | +0.00 |
| evidence_from_delegated_sources | 1.00 | 1.00 | +0.00 |
| evidence_status_matches_findings | 0.89 | — | — |
| graph_path_valid | 1.00 | 1.00 | +0.00 |
| no_live_evidence_from_unavailable | 1.00 | 0.96 | +0.04 |
| report_grounded_in_findings | 1.00 | 1.00 | +0.00 |
| report_has_required_fields | 1.00 | 1.00 | +0.00 |
| root_cause_identified | 1.00 | 1.00 | +0.00 |
| safe_remediation | 1.00 | 1.00 | +0.00 |

## How to run

From `apps/api`:

```powershell
pip install -e ".[dev,eval]"
python -m evaluation.run --suite all
python -m evaluation.upload_evaluators
python -m evaluation.summary
```
