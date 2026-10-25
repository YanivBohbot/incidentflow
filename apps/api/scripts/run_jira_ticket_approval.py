"""Retired: Jira writes must use the human-approved IncidentFlow API route."""


def main() -> int:
    print(
        "The simulated Jira write demo was retired. Use POST "
        "/api/jira/investigations/{investigation_id}/issues with approved=true "
        "and JIRA_MCP_WRITE_ENABLED=true."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
