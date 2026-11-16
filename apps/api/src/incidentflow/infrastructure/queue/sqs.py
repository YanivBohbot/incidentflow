import json
import logging
from typing import Any
from uuid import UUID

import boto3

from incidentflow.application.jobs.queue import JobQueue, ReceivedJob
from incidentflow.core.config import Settings

logger = logging.getLogger(__name__)


class SqsJobQueue:
    """JobQueue backed by SQS (or ElasticMQ locally via SQS_ENDPOINT_URL)."""

    def __init__(self, client: Any, queue_url: str) -> None:
        self._client = client
        self._queue_url = queue_url

    def send(self, investigation_id: UUID) -> None:
        self._client.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps({"investigation_id": str(investigation_id)}),
        )

    def receive(self, *, max_messages: int, wait_seconds: int) -> list[ReceivedJob]:
        response = self._client.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_seconds,
        )
        jobs: list[ReceivedJob] = []
        for message in response.get("Messages", []):
            receipt = message["ReceiptHandle"]
            try:
                investigation_id = UUID(json.loads(message["Body"])["investigation_id"])
            except (ValueError, KeyError, TypeError, AttributeError):
                logger.warning("Dropping malformed job queue message %s", message.get("MessageId"))
                self._client.delete_message(QueueUrl=self._queue_url, ReceiptHandle=receipt)
                continue
            jobs.append(ReceivedJob(investigation_id=investigation_id, receipt=receipt))
        return jobs

    def ack(self, job: ReceivedJob) -> None:
        self._client.delete_message(QueueUrl=self._queue_url, ReceiptHandle=job.receipt)

    def extend(self, job: ReceivedJob, *, visibility_seconds: int) -> None:
        self._client.change_message_visibility(
            QueueUrl=self._queue_url,
            ReceiptHandle=job.receipt,
            VisibilityTimeout=visibility_seconds,
        )


# ElasticMQ ignores signatures but boto3 still needs credentials to sign. They are passed to
# this client only, never exported: process-wide AWS_* keys would leak into the CloudWatch MCP
# subprocess and override its AWS_PROFILE.
LOCAL_QUEUE_CREDENTIALS = {"aws_access_key_id": "local", "aws_secret_access_key": "local"}


def build_job_queue(settings: Settings) -> JobQueue:
    endpoint_url = settings.sqs_endpoint_url or None
    credentials = LOCAL_QUEUE_CREDENTIALS if endpoint_url else {}
    client = boto3.client(
        "sqs",
        endpoint_url=endpoint_url,
        region_name=settings.queue_region,
        **credentials,
    )
    return SqsJobQueue(client, settings.job_queue_url)
