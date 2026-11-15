import json
from uuid import UUID, uuid4

import boto3
from botocore.stub import Stubber

from incidentflow.application.jobs.queue import InMemoryJobQueue, ReceivedJob
from incidentflow.infrastructure.queue.sqs import SqsJobQueue

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
