"""Stable, UI-safe option models extracted from untrusted Jira MCP responses."""

import json
from typing import Any

from pydantic import BaseModel


class JiraResourceOption(BaseModel):
    cloud_id: str
    url: str | None = None


class JiraProjectOption(BaseModel):
    key: str
    name: str


class JiraIssueTypeOption(BaseModel):
    id: str
    name: str


def extract_jira_data(result: Any) -> dict[str, Any]:
    """Extract the first JSON data envelope returned by an MCP text content block."""
    blocks = result if isinstance(result, list) else []
    for block in blocks:
        if not isinstance(block, dict) or not isinstance(block.get("text"), str):
            continue
        try:
            payload = json.loads(block["text"])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            return payload["data"]
    return {}


def resource_options(result: Any) -> list[JiraResourceOption]:
    resources = extract_jira_data(result).get("resources", [])
    if not isinstance(resources, list):
        return []
    return [
        JiraResourceOption(cloud_id=item["cloudId"], url=item.get("url"))
        for item in resources
        if isinstance(item, dict) and isinstance(item.get("cloudId"), str)
    ]


def project_options(result: Any) -> list[JiraProjectOption]:
    projects = extract_jira_data(result).get("values", [])
    if not isinstance(projects, list):
        return []
    return [
        JiraProjectOption(key=item["key"], name=item.get("name", item["key"]))
        for item in projects
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    ]


def issue_type_options(result: Any) -> list[JiraIssueTypeOption]:
    data = extract_jira_data(result)
    candidates = data.get("issueTypes", data.get("values", []))
    if not isinstance(candidates, list):
        return []
    return [
        JiraIssueTypeOption(
            id=str(item.get("id", item.get("name"))),
            name=str(item.get("name", item.get("id"))),
        )
        for item in candidates
        if isinstance(item, dict) and (item.get("id") is not None or item.get("name") is not None)
    ]
