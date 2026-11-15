import json
from uuid import UUID, uuid4

import boto3
import pytest
from botocore.stub import Stubber

from incidentflow.application.jobs.queue import InMemoryJobQueue, ReceivedJob
from incidentflow.core.config import Settings
from incidentflow.infrastructure.queue import sqs
from incidentflow.infrastructure.queue.sqs import SqsJobQueue, build_job_queue

QUEUE_URL = "http://localhost:9324/000000000000/incidentflow-investigations"


def _sqs_client():
    return boto3.client(
        "sqs",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        endpoint_url="http://localhost:9324",
    )


def test_in_memory_queue_round_trip() -> None:
    queue = InMemoryJobQueue()
    first, second = uuid4(), uuid4()
    queue.send(first)
    queue.send(second)

    jobs = queue.receive(max_messages=5, wait_seconds=0)

    assert [job.investigation_id for job in jobs] == [first, second]
    assert queue.receive(max_messages=5, wait_seconds=0) == []
    queue.ack(jobs[0])
    assert queue.sent == [first, second]
    assert queue.acked == [jobs[0]]


def test_sqs_queue_uses_expected_requests() -> None:
    client = _sqs_client()
    investigation_id = uuid4()
    with Stubber(client) as stubber:
        stubber.add_response(
            "send_message",
            {"MessageId": "m1", "MD5OfMessageBody": "x"},
            {
                "QueueUrl": QUEUE_URL,
                "MessageBody": json.dumps({"investigation_id": str(investigation_id)}),
            },
        )
        stubber.add_response(
            "receive_message",
            {
                "Messages": [
                    {
                        "MessageId": "m1",
                        "ReceiptHandle": "receipt-1",
                        "Body": json.dumps({"investigation_id": str(investigation_id)}),
                    }
                ]
            },
            {"QueueUrl": QUEUE_URL, "MaxNumberOfMessages": 2, "WaitTimeSeconds": 10},
        )
        stubber.add_response("delete_message", {}, {"QueueUrl": QUEUE_URL, "ReceiptHandle": "r"})
        stubber.add_response(
            "change_message_visibility",
            {},
            {"QueueUrl": QUEUE_URL, "ReceiptHandle": "r", "VisibilityTimeout": 300},
        )
        queue = SqsJobQueue(client, QUEUE_URL)

        queue.send(investigation_id)
        jobs = queue.receive(max_messages=2, wait_seconds=10)
        assert jobs == [ReceivedJob(investigation_id=investigation_id, receipt="receipt-1")]
        queue.ack(ReceivedJob(investigation_id=investigation_id, receipt="r"))
        queue.extend(
            ReceivedJob(investigation_id=investigation_id, receipt="r"), visibility_seconds=300
        )

        stubber.assert_no_pending_responses()


def test_sqs_receive_skips_malformed_body() -> None:
    client = _sqs_client()
    valid_id = uuid4()
    with Stubber(client) as stubber:
        stubber.add_response(
            "receive_message",
            {
                "Messages": [
                    {"MessageId": "m1", "ReceiptHandle": "bad", "Body": "x"},
                    {
                        "MessageId": "m2",
                        "ReceiptHandle": "bad-uuid",
                        "Body": '{"investigation_id": "nope"}',
                    },
                    {
                        "MessageId": "m3",
                        "ReceiptHandle": "good",
                        "Body": json.dumps({"investigation_id": str(valid_id)}),
                    },
                ]
            },
            {"QueueUrl": QUEUE_URL, "MaxNumberOfMessages": 3, "WaitTimeSeconds": 0},
        )
        stubber.add_response("delete_message", {}, {"QueueUrl": QUEUE_URL, "ReceiptHandle": "bad"})
        stubber.add_response(
            "delete_message", {}, {"QueueUrl": QUEUE_URL, "ReceiptHandle": "bad-uuid"}
        )
        queue = SqsJobQueue(client, QUEUE_URL)

        jobs = queue.receive(max_messages=3, wait_seconds=0)

        assert jobs == [ReceivedJob(investigation_id=valid_id, receipt="good")]
        assert isinstance(jobs[0].investigation_id, UUID)
        stubber.assert_no_pending_responses()


AWS_CREDENTIAL_ENV_VARS = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
)


def _queue_settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite://",
        openai_api_key="test",
        **overrides,
    )


@pytest.fixture
def no_aws_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    for name in AWS_CREDENTIAL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "missing-credentials"))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "missing-config"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


def test_build_job_queue_with_endpoint_signs_without_aws_env_vars(
    no_aws_credentials: None,
) -> None:
    queue = build_job_queue(_queue_settings(sqs_endpoint_url="http://localhost:9324"))

    assert isinstance(queue, SqsJobQueue)
    credentials = queue._client._request_signer._credentials
    assert credentials is not None
    assert credentials.access_key == "local"
    assert credentials.secret_key == "local"


def test_build_job_queue_without_endpoint_passes_no_explicit_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_client(service_name: str, **kwargs: object) -> object:
        calls.append({"service_name": service_name, **kwargs})
        return object()

    monkeypatch.setattr(sqs.boto3, "client", fake_client)

    build_job_queue(_queue_settings(sqs_endpoint_url=None))

    assert len(calls) == 1
    assert calls[0]["service_name"] == "sqs"
    assert calls[0].get("endpoint_url") is None
    assert "aws_access_key_id" not in calls[0]
    assert "aws_secret_access_key" not in calls[0]


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_sqs_endpoint_url_is_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch, no_aws_credentials: None, value: str
) -> None:
    monkeypatch.setenv("SQS_ENDPOINT_URL", value)

    settings = _queue_settings()

    assert settings.sqs_endpoint_url is None
    build_job_queue(settings)
