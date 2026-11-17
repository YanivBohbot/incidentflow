from incidentflow.agent.findings import CausalStep, InvestigationReport
from incidentflow.agent.prompts.supervisor import SUPERVISOR_SYSTEM_PROMPT


def test_reports_saved_before_the_causal_chain_still_load() -> None:
    report = InvestigationReport.model_validate({"summary": "Checkout is down.", "confidence": 0.8})

    assert report.root_cause is None
    assert report.causal_chain == []


def test_report_keeps_the_causal_chain_in_order() -> None:
    report = InvestigationReport.model_validate(
        {
            "summary": "Checkout is down.",
            "confidence": 0.9,
            "root_cause": "The database connection pool is exhausted by the flash-sale traffic.",
            "causal_chain": [
                {
                    "label": "Traffic spike",
                    "detail": "Requests rose from 400 to 2100 per second.",
                    "source": "data_intelligence",
                    "verified": True,
                },
                {
                    "label": "Pool exhausted",
                    "detail": "200 of 200 connections in use, waits above 5 s.",
                    "source": "cloudwatch",
                    "verified": True,
                },
                {
                    "label": "HTTP 503 for customers",
                    "detail": "42% of POST /checkout fail.",
                    "source": "cloudwatch",
                    "verified": False,
                },
            ],
        }
    )

    assert [step.label for step in report.causal_chain] == [
        "Traffic spike",
        "Pool exhausted",
        "HTTP 503 for customers",
    ]
    assert isinstance(report.causal_chain[0], CausalStep)
    assert report.causal_chain[2].verified is False


def test_supervisor_is_asked_for_a_root_cause_and_causal_chain() -> None:
    assert "root_cause" in SUPERVISOR_SYSTEM_PROMPT
    assert "causal_chain" in SUPERVISOR_SYSTEM_PROMPT


def test_supervisor_ends_the_chain_with_the_customer_symptom() -> None:
    assert "last step must be the customer-visible symptom" in SUPERVISOR_SYSTEM_PROMPT
    assert "contributing factors" in SUPERVISOR_SYSTEM_PROMPT


def test_supervisor_lowers_confidence_for_hypotheses_and_synthetic_data() -> None:
    assert "Lower confidence" in SUPERVISOR_SYSTEM_PROMPT
    assert "synthetic" in SUPERVISOR_SYSTEM_PROMPT
    assert "never above 0.7" in SUPERVISOR_SYSTEM_PROMPT


def test_supervisor_always_proposes_next_actions() -> None:
    assert "two to four proposed_actions" in SUPERVISOR_SYSTEM_PROMPT
    assert "even when a Jira issue" in SUPERVISOR_SYSTEM_PROMPT
