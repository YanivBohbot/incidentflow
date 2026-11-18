# Evaluation summary

## incidentflow-supervisor-trajectory

Latest experiment: [trajectory-307e2905](https://smith.langchain.com/o/c920c557-3266-4d89-b818-f7e709fe4965/projects/p/45003e35-00ae-426e-b038-f572abe3c525)
Previous experiment: [trajectory-cac1bed1](https://smith.langchain.com/o/c920c557-3266-4d89-b818-f7e709fe4965/projects/p/eb5e75b1-f489-4c53-9bea-978db421bb60)
Run settings: model: gpt-4.1-mini, judge_model: gpt-4.1, prompt_hash: 127cb5e718c0

| Metric | Latest | Previous | Δ |
| --- | --- | --- | --- |
| delegation_args_contain_key_facts | 1.00 | 1.00 | +0.00 |
| delegation_calls_within_limit | 1.00 | 1.00 | +0.00 |
| forbidden_specialists_not_called | 1.00 | 1.00 | +0.00 |
| investigation_path_reasonable | 0.88 | 0.88 | +0.00 |
| required_specialists_called | 1.00 | 1.00 | +0.00 |

## incidentflow-investigation-reports

Latest experiment: [reports-af351fbb](https://smith.langchain.com/o/c920c557-3266-4d89-b818-f7e709fe4965/projects/p/4e4bd3ca-7ce6-483d-94f4-cb8f9fd0a9d0)
Previous experiment: [reports-2ccbc5a5](https://smith.langchain.com/o/c920c557-3266-4d89-b818-f7e709fe4965/projects/p/ce4cf7cc-985c-4b40-8b1e-f548d59be7ba)
Run settings: model: gpt-4.1-mini, judge_model: gpt-4.1, prompt_hash: 127cb5e718c0

| Metric | Latest | Previous | Δ |
| --- | --- | --- | --- |
| evidence_attributed | 1.00 | 1.00 | +0.00 |
| evidence_from_delegated_sources | 0.85 | 0.96 | -0.11 |
| graph_path_valid | 1.00 | 1.00 | +0.00 |
| no_live_evidence_from_unavailable | 1.00 | 1.00 | +0.00 |
| report_grounded_in_findings | 1.00 | 1.00 | +0.00 |
| report_has_required_fields | 1.00 | 1.00 | +0.00 |
| root_cause_identified | 1.00 | 0.85 | +0.15 |
| safe_remediation | 1.00 | 1.00 | +0.00 |

## How to run

From `apps/api`:

```powershell
pip install -e ".[dev,eval]"
python -m evaluation.run --suite all
python -m evaluation.upload_evaluators
python -m evaluation.summary
```
