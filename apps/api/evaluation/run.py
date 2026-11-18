"""Run the trajectory and reports evaluation suites as LangSmith experiments.

Usage: python -m evaluation.run --suite trajectory|reports|all [--live-integrations]
Specialist findings are replayed from fixtures; Jira, MongoDB, GitHub, and CloudWatch stay
disabled unless --live-integrations is passed.
"""

import argparse
import asyncio
import os

LIVE_INTEGRATION_FLAGS = (
    "JIRA_MCP_ENABLED",
    "MONGODB_MCP_ENABLED",
    "GITHUB_MCP_ENABLED",
    "CLOUDWATCH_MCP_ENABLED",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["trajectory", "reports", "all"], required=True)
    parser.add_argument(
        "--live-integrations",
        action="store_true",
        help="Run the real specialists as configured in .env instead of frozen findings.",
    )
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--max-concurrency", type=int, default=1)
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if not args.live_integrations:
        # Environment variables take precedence over .env, so set them before reading settings.
        for flag in LIVE_INTEGRATION_FLAGS:
            os.environ[flag] = "false"

    from langsmith import Client

    from evaluation.harness.runner import run_suite
    from incidentflow.core.config import get_settings

    get_settings.cache_clear()
    client = Client()
    suites = ["trajectory", "reports"] if args.suite == "all" else [args.suite]
    for suite in suites:
        await run_suite(
            suite,
            live=args.live_integrations,
            repetitions=args.repetitions,
            max_concurrency=args.max_concurrency,
            client=client,
        )


if __name__ == "__main__":
    asyncio.run(main())
