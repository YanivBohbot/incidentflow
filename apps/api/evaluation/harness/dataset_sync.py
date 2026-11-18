"""Idempotent sync of scenario examples into a LangSmith dataset (never deletes examples)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class SyncResult:
    created: int
    updated: int
    unchanged: int


def _unchanged(existing: Any, spec: dict[str, Any]) -> bool:
    # Server-side metadata keys (e.g. dataset_split) are ignored: only ours must match.
    metadata = existing.metadata or {}
    return (
        (existing.inputs or {}) == spec["inputs"]
        and (existing.outputs or {}) == spec["outputs"]
        and all(metadata.get(key) == value for key, value in spec["metadata"].items())
    )


def sync_dataset(
    client: Any, name: str, description: str, examples: list[dict[str, Any]]
) -> SyncResult:
    """Create the dataset and examples if missing, update changed ones, tag a new version."""
    if not client.has_dataset(dataset_name=name):
        client.create_dataset(name, description=description)
        existing: dict[str, Any] = {}
    else:
        existing = {
            (example.metadata or {}).get("scenario"): example
            for example in client.list_examples(dataset_name=name)
        }

    to_create: list[dict[str, Any]] = []
    updated = unchanged = 0
    for spec in examples:
        current = existing.get(spec["metadata"]["scenario"])
        if current is None:
            to_create.append(spec)
        elif _unchanged(current, spec):
            unchanged += 1
        else:
            client.update_example(
                current.id,
                inputs=spec["inputs"],
                outputs=spec["outputs"],
                metadata={**(current.metadata or {}), **spec["metadata"]},
            )
            updated += 1
    if to_create:
        client.create_examples(dataset_name=name, examples=to_create)

    if to_create or updated:
        now = datetime.now(UTC)
        client.update_dataset_tag(
            dataset_name=name, as_of=now, tag="v" + now.strftime("%Y%m%d%H%M")
        )
    return SyncResult(created=len(to_create), updated=updated, unchanged=unchanged)
