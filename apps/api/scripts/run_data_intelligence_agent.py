"""Run the read-only Data Intelligence Agent against a live MongoDB MCP connection."""

import argparse
import asyncio

from langchain_openai.chat_models.base import OpenAIAuthenticationError

from incidentflow.agent.findings import DataIntelligenceFinding
from incidentflow.agent.identities import DATA_INTELLIGENCE_AGENT
from incidentflow.agent.tools.data_intelligence_tools import ask_data_intelligence
from incidentflow.core.config import get_settings

DEFAULT_INCIDENT = (
    "Payment API has returned HTTP 500 errors. Inspect the live MongoDB operational "
    "events, construct a time-ordered technical summary, and keep hypotheses separate "
    "from observed evidence."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--incident",
        default=DEFAULT_INCIDENT,
        help="Incident description to investigate.",
    )
    return parser.parse_args()


async def run(incident: str) -> None:
    settings = get_settings()
    if not settings.mongodb_mcp_enabled:
        raise RuntimeError("Set MONGODB_MCP_ENABLED=true before running this live MongoDB demo.")

    finding_json = await ask_data_intelligence.ainvoke({"incident_context": incident})
    finding = DataIntelligenceFinding.model_validate_json(finding_json)
    if finding.confidence == 0 and not finding.evidence:
        finding = DataIntelligenceFinding(
        summary="MongoDB investigation stopped before a structured finding was produced.",
        timeline=[],
        error_signatures=[],
        evidence=[],
        suspected_root_causes=[],
        confidence=0,
        )
    print("\n[structured_response]")
    print(finding.model_dump_json(indent=2))


def main() -> int:
    args = parse_args()
    print(f"Running {DATA_INTELLIGENCE_AGENT.display_name}...")

    try:
        asyncio.run(run(args.incident))
    except OpenAIAuthenticationError:
        print("OpenAI authentication failed. Verify OPENAI_API_KEY without printing it.")
        return 1
    except RuntimeError as error:
        print(error)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
