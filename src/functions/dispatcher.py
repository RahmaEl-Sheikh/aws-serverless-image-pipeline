"""SQS consumer: turns S3 upload events into Step Functions executions.

* One execution per uploaded object.
* The execution name is the imageId, so a duplicate SQS delivery (SQS is
  at-least-once) hits ExecutionAlreadyExists and is treated as success -
  i.e. processing is idempotent.
* Partial batch responses: only the failed messages go back to the queue,
  and after 3 receives they move to the dead-letter queue.
"""
import json
import os
import re
from urllib.parse import unquote_plus

import boto3

from common import log

_sfn = None
KEY_PATTERN = re.compile(r"^uploads/(?P<image_id>[0-9a-f]{32})/[^/]+$")


def sfn_client():
    global _sfn
    if _sfn is None:
        _sfn = boto3.client("stepfunctions")
    return _sfn


def parse_s3_records(body: str):
    event = json.loads(body)
    if event.get("Event") == "s3:TestEvent":  # sent once when the notification is configured
        return []
    jobs = []
    for record in event.get("Records", []):
        if not record.get("eventName", "").startswith("ObjectCreated"):
            continue
        key = unquote_plus(record["s3"]["object"]["key"])
        match = KEY_PATTERN.match(key)
        if not match:
            log("Skipping object outside the expected key layout", key=key)
            continue
        jobs.append(
            {
                "imageId": match.group("image_id"),
                "bucket": record["s3"]["bucket"]["name"],
                "key": key,
                "size": record["s3"]["object"].get("size"),
                "eTag": record["s3"]["object"].get("eTag"),
            }
        )
    return jobs


def start_execution(job: dict):
    client = sfn_client()
    try:
        response = client.start_execution(
            stateMachineArn=os.environ["STATE_MACHINE_ARN"],
            name=job["imageId"],
            input=json.dumps(job),
        )
        log("Started execution", imageId=job["imageId"], executionArn=response["executionArn"])
    except client.exceptions.ExecutionAlreadyExists:
        log("Execution already exists - duplicate delivery ignored", imageId=job["imageId"])


def handler(event, _context):
    failures = []
    for message in event.get("Records", []):
        try:
            for job in parse_s3_records(message["body"]):
                start_execution(job)
        except Exception as exc:  # noqa: BLE001 - report the single message as failed
            log("Failed to dispatch message", messageId=message["messageId"], error=repr(exc))
            failures.append({"itemIdentifier": message["messageId"]})
    return {"batchItemFailures": failures}
