"""Create the demo incidents that match scripts/seed_mongodb_scenarios.js.

Each incident has a different nature and severity so an operator can pick one and watch which
agents the supervisor chooses. Some ask for a Jira write, which pauses for human approval.

Usage (API running):  python scripts/seed_demo_scenarios.py [--api http://127.0.0.1:8000]
The script is idempotent: an incident whose title already exists is skipped.
"""

import argparse

import httpx

JIRA_PROJECT = "SAM1"

SCENARIOS = [
    {
        "priority": "CRITICAL",
        "title": "[Demo] Checkout down during flash sale (checkout-api)",
        "description": (
            "checkout-api returns HTTP 503 on POST /checkout for about 40% of customers since the "
            "flash sale started. Check the operational events and the runbook for connection pool "
            f"exhaustion. Create a Jira issue of type Task in Jira project {JIRA_PROJECT} so the "
            "on-call team can track the outage."
        ),
    },
    {
        "priority": "CRITICAL",
        "title": "[Demo] Customers report missing orders (order-service)",
        "description": (
            "Customers say their confirmed orders are missing from their order history, but "
            "order-service dashboards look healthy. Check order-service operational events and "
            "explain whether the orders were lost or only not visible."
        ),
    },
    {
        "priority": "HIGH",
        "title": "[Demo] Login failures after key rotation (auth-service)",
        "description": (
            "Many customers cannot log in: auth-service returns HTTP 401 since this morning's "
            "JWT signing-key rotation. Check auth-service events, recent code changes, and the "
            "incident runbook."
        ),
    },
    {
        "priority": "HIGH",
        "title": "[Demo] inventory-service pods restarting (OOMKilled)",
        "description": (
            "inventory-service pods keep restarting with OOMKilled since release 2.4.1, and stock "
            "reads fail during restarts. Check inventory-service events for a memory leak. Create a "
            f"Jira issue of type Task in Jira project {JIRA_PROJECT} for the memory leak."
        ),
    },
    {
        "priority": "HIGH",
        "title": "[Demo] Refund requests failing (refund-service)",
        "description": (
            "refund-service rejects about 25% of POST /refunds with HTTP 502, so customers cannot "
            "get their money back. Check refund-service alarms, logs, operational events, recent "
            "code changes, and the runbook for upstream payment-gateway errors. Create a Jira "
            f"issue of type Task in Jira project {JIRA_PROJECT} so the payments on-call team can "
            "track the refund outage."
        ),
    },
    {
        "priority": "MEDIUM",
        "title": "[Demo] payment-service HTTP 500 alarm (CloudWatch)",
        "description": (
            "The CloudWatch alarm for payment-service HTTP 5xx errors fired. Check production "
            "alarms, metrics, and logs, plus the payment-service operational events."
        ),
    },
    {
        "priority": "MEDIUM",
        "title": "[Demo] Slow search results (search-api)",
        "description": (
            "search-api answers slowly: p95 latency went from about 200 ms to more than 2 s. "
            "Check search-api events for the cause and say whether it is recovering."
        ),
    },
    {
        "priority": "LOW",
        "title": "[Demo] Delayed notification emails (notification-service)",
        "description": (
            "Order confirmation emails from notification-service arrive about 15 minutes late. "
            "Check notification-service events and confirm whether any email was lost."
        ),
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="IncidentFlow API base URL")
    api = parser.parse_args().api.rstrip("/")

    with httpx.Client(base_url=f"{api}/api", timeout=30) as client:
        existing = {
            incident["title"] for incident in client.get("/incidents").raise_for_status().json()
        }
        for scenario in SCENARIOS:
            if scenario["title"] in existing:
                print(f"skip    {scenario['priority']:<8} {scenario['title']}")
                continue
            client.post("/incidents", json=scenario).raise_for_status()
            print(f"created {scenario['priority']:<8} {scenario['title']}")


if __name__ == "__main__":
    main()
