from incidentflow.agent.findings import CausalStep, InvestigationEvidence, InvestigationReport
from incidentflow.agent.orchestration.investigation_workflow import capture_supervisor_report
from incidentflow.agent.orchestration.policies.confidence import cap_confidence


def step(source: str, verified: bool = True) -> CausalStep:
    return CausalStep(label="Step", detail="Detail.", source=source, verified=verified)


def evidence(source: str, status: str = "live") -> InvestigationEvidence:
    return InvestigationEvidence(source=source, detail="Detail.", source_status=status)


def report(confidence: float, chain: list[CausalStep], found: list[InvestigationEvidence]):
    return InvestigationReport(
        summary="Checkout is down.", confidence=confidence, causal_chain=chain, evidence=found
    )


def test_a_chain_from_a_single_specialist_is_capped_at_ninety_percent() -> None:
    capped = cap_confidence(
        report(
            0.95,
            [step("ask_data_intelligence"), step("ask_data_intelligence")],
            [evidence("ask_data_intelligence")],
        )
    )

    assert capped.confidence == 0.9
    assert capped.limitations == ["Confidence capped at 90%: the causal chain rests on one source."]


def test_a_hypothesis_in_the_chain_caps_confidence_at_eighty_percent() -> None:
    capped = cap_confidence(
        report(
            0.95,
            [step("ask_github", verified=False), step("ask_cloudwatch")],
            [evidence("ask_github"), evidence("ask_cloudwatch")],
        )
    )

    assert capped.confidence == 0.8


def test_simulated_evidence_caps_confidence_at_seventy_percent() -> None:
    capped = cap_confidence(
        report(
            0.95,
            [step("ask_github"), step("ask_data_intelligence")],
            [evidence("ask_github"), evidence("ask_data_intelligence", "simulated")],
        )
    )

    assert capped.confidence == 0.7
    assert "synthetic or simulated" in capped.limitations[0]


def test_a_well_supported_report_keeps_its_confidence() -> None:
    original = report(
        0.95,
        [step("ask_github"), step("ask_cloudwatch")],
        [evidence("ask_github"), evidence("ask_cloudwatch")],
    )

    assert cap_confidence(original) == original


def test_capping_twice_adds_the_limitation_once() -> None:
    once = cap_confidence(report(0.95, [step("ask_cloudwatch")], [evidence("ask_cloudwatch")]))

    assert cap_confidence(once).limitations == once.limitations


def test_the_cap_is_applied_when_the_supervisor_report_is_captured() -> None:
    raw = report(1.0, [step("ask_cloudwatch")], [evidence("ask_cloudwatch")])

    captured = capture_supervisor_report({"structured_response": raw})

    assert captured["report"].confidence == 0.9


def test_a_step_citing_two_specialists_counts_as_two_sources() -> None:
    original = report(
        0.95,
        [step("ask_data_intelligence, ask_cloudwatch"), step("ask_data_intelligence")],
        [evidence("ask_data_intelligence"), evidence("ask_cloudwatch")],
    )

    assert cap_confidence(original) == original


def test_two_spellings_of_one_specialist_still_count_as_one_source() -> None:
    capped = cap_confidence(
        report(
            0.95,
            [step("ask_cloudwatch"), step("cloudwatch")],
            [evidence("ask_cloudwatch")],
        )
    )

    assert capped.confidence == 0.9


def test_specialists_joined_with_and_count_separately() -> None:
    original = report(
        0.95,
        [step("ask_github and ask_cloudwatch")],
        [evidence("ask_github"), evidence("ask_cloudwatch")],
    )

    assert cap_confidence(original) == original
