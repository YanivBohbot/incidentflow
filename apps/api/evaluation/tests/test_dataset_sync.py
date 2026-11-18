from datetime import datetime
from types import SimpleNamespace
from typing import Any

from evaluation.harness.dataset_sync import SyncResult, sync_dataset


class FakeClient:
    def __init__(self, examples: list[dict[str, Any]] | None = None, exists: bool = True) -> None:
        self.exists = exists
        self.examples = {f"id-{i}": dict(example) for i, example in enumerate(examples or [])}
        self.created_datasets: list[dict[str, Any]] = []
        self.create_calls: list[list[dict[str, Any]]] = []
        self.update_calls: list[dict[str, Any]] = []
        self.tag_calls: list[dict[str, Any]] = []

    def has_dataset(self, *, dataset_name: str) -> bool:
        return self.exists

    def create_dataset(self, dataset_name: str, *, description: str | None = None) -> None:
        self.exists = True
        self.created_datasets.append({"name": dataset_name, "description": description})

    def list_examples(self, *, dataset_name: str) -> list[Any]:
        return [SimpleNamespace(id=key, **value) for key, value in self.examples.items()]

    def create_examples(self, *, dataset_name: str, examples: list[dict[str, Any]]) -> None:
        self.create_calls.append(examples)
        for example in examples:
            self.examples[f"new-{len(self.examples)}"] = dict(example)

    def update_example(self, example_id: str, *, inputs: Any, outputs: Any, metadata: Any) -> None:
        self.update_calls.append({"id": example_id})
        self.examples[example_id] = {"inputs": inputs, "outputs": outputs, "metadata": metadata}

    def update_dataset_tag(self, *, dataset_name: str, as_of: datetime, tag: str) -> None:
        self.tag_calls.append({"name": dataset_name, "as_of": as_of, "tag": tag})


def _spec(name: str, outputs: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "inputs": {"incident_request": f"request {name}", "scenario": name},
        "outputs": outputs or {"required_specialists": ["ask_knowledge"]},
        "metadata": {"scenario": name},
    }


def test_sync_creates_missing_examples_and_dataset() -> None:
    client = FakeClient(exists=False)

    result = sync_dataset(client, "ds", "a dataset", [_spec("a"), _spec("b")])

    assert result == SyncResult(created=2, updated=0, unchanged=0)
    assert client.created_datasets == [{"name": "ds", "description": "a dataset"}]
    assert len(client.create_calls) == 1 and len(client.create_calls[0]) == 2
    assert len(client.tag_calls) == 1


def test_sync_updates_changed_example_by_scenario_name() -> None:
    old = {
        "inputs": {"incident_request": "old request"},
        "outputs": {"required_specialists": ["ask_knowledge"], "unavailable_sources": []},
        "metadata": {"scenario": "EVAL-PAY-001"},
    }
    client = FakeClient([old])

    result = sync_dataset(client, "ds", "d", [_spec("EVAL-PAY-001")])

    assert result == SyncResult(created=0, updated=1, unchanged=0)
    assert client.update_calls == [{"id": "id-0"}]
    assert len(client.examples) == 1
    assert client.create_calls == []
    assert client.examples["id-0"]["inputs"]["scenario"] == "EVAL-PAY-001"
    assert len(client.tag_calls) == 1


def test_sync_second_run_is_a_noop_and_does_not_tag() -> None:
    client = FakeClient(exists=False)
    specs = [_spec("a"), _spec("b")]
    sync_dataset(client, "ds", "d", specs)
    client.tag_calls.clear()

    result = sync_dataset(client, "ds", "d", specs)

    assert result == SyncResult(created=0, updated=0, unchanged=2)
    assert len(client.create_calls) == 1
    assert client.update_calls == []
    assert client.tag_calls == []


def test_sync_tags_with_utc_timestamp_and_never_deletes_extra_examples() -> None:
    client = FakeClient([_spec("extra")])

    sync_dataset(client, "ds", "d", [_spec("a")])

    assert len(client.examples) == 2
    tag = client.tag_calls[0]
    assert tag["tag"] == "v" + tag["as_of"].strftime("%Y%m%d%H%M")
    assert tag["as_of"].tzinfo is not None
    assert tag["name"] == "ds"


def test_sync_ignores_extra_server_side_metadata_keys() -> None:
    existing = _spec("a")
    existing["metadata"] = {"scenario": "a", "dataset_split": ["base"]}
    client = FakeClient([existing])

    result = sync_dataset(client, "ds", "d", [_spec("a")])

    assert result.unchanged == 1 and client.tag_calls == []
