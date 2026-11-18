# Evaluation summary

## incidentflow-supervisor-trajectory

Latest experiment: [trajectory-1c5f832b](https://smith.langchain.com/o/c920c557-3266-4d89-b818-f7e709fe4965/projects/p/a5a5ccd4-a4a7-4705-9d65-b3c57cde7147)
Previous experiment: [trajectory-5ed1d16f](https://smith.langchain.com/o/c920c557-3266-4d89-b818-f7e709fe4965/projects/p/e9c006dc-f519-4864-a5b2-0f3defc4eb6a)
Run settings: model: gpt-4.1-mini, judge_model: gpt-4.1, prompt_hash: 57f4a27cc516

| Metric | Latest | Previous | Δ |
| --- | --- | --- | --- |
| delegation_args_contain_key_facts | 1.00 | 1.00 | +0.00 |
| delegation_calls_within_limit | 1.00 | 1.00 | +0.00 |
| forbidden_specialists_not_called | 0.88 | 0.88 | +0.00 |
| investigation_path_reasonable | 1.00 | 0.96 | +0.04 |
| required_specialists_called | 1.00 | 1.00 | +0.00 |

## incidentflow-investigation-reports

Latest experiment: [reports-c567e99d](https://smith.langchain.com/o/c920c557-3266-4d89-b818-f7e709fe4965/projects/p/80fa5817-52e4-4549-8954-c3c00fe8b098)
Previous experiment: [reports-3a93dda7](https://smith.langchain.com/o/c920c557-3266-4d89-b818-f7e709fe4965/projects/p/46f7ba83-b6b9-4749-b4c4-9509c1866dbb)
Run settings: model: gpt-4.1-mini, judge_model: gpt-4.1, prompt_hash: 57f4a27cc516

| Metric | Latest | Previous | Δ |
| --- | --- | --- | --- |
| evidence_attributed | 1.00 | 0.96 | +0.04 |
| evidence_from_delegated_sources | 1.00 | 0.96 | +0.04 |
| graph_path_valid | 1.00 | 0.96 | +0.04 |
| no_live_evidence_from_unavailable | 0.96 | 0.93 | +0.04 |
| report_grounded_in_findings | 1.00 | 0.96 | +0.04 |
| report_has_required_fields | 1.00 | 0.96 | +0.04 |
| root_cause_identified | 0.88 | 0.85 | +0.03 |
| safe_remediation | 1.00 | 0.96 | +0.04 |

## How to run

From `apps/api`:

```powershell
pip install -e ".[dev,eval]"
python -m evaluation.run --suite all
python -m evaluation.upload_evaluators
python -m evaluation.summary
```
