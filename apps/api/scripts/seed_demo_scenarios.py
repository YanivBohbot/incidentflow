"""Create the demo incidents that match scripts/seed_mongodb_scenarios.js.

Each incident has a different nature and severity so an operator can pick one and watch which
agents the supervisor chooses. Some ask for a Jira write, which pauses for human approval.

Usage (API running):  python scripts/seed_demo_scenarios.py [--api http://127.0.0.1:8000]
The script is idempotent: an incident whose title already exists is skipped.
"""

import argparse

import httpx

from incidentflow.demo.scenarios import SCENARIOS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="IncidentFlow API base URL")
    api = parser.parse_args().api.rstrip("/")

    with httpx.Client(base_url=f"{api}/api", timeout=30) as client:
        existing = {
            incident["title"] for incident in client.get("/incidents").raise_for_status().json()
        }
        for scenario in SCENARIOS:
            priority = scenario.priority.value
            if scenario.title in existing:
                print(f"skip    {priority:<8} {scenario.title}")
                continue
            payload = {
                "title": scenario.title,
                "description": scenario.description,
                "priority": priority,
            }
            client.post("/incidents", json=payload).raise_for_status()
            print(f"created {priority:<8} {scenario.title}")


if __name__ == "__main__":
    main()
