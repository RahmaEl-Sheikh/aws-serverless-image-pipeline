"""POST /uploads - issue a pre-signed S3 POST so the browser uploads straight to S3.

The POST policy is enforced by S3 itself: exact key, exact Content-Type,
size range and a 5-minute expiry. Image bytes never pass through API
Gateway or Lambda (no 10 MB payload limit, no compute cost).
"""
import json
import os
import re
import uuid
from datetime import datetime, timezone

import boto3
from botocore.config import Config

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
URL_TTL_SECONDS = 300

_s3 = None
_table = None


def s3_client():
    global _s3
    if _s3 is None:
        region = os.environ.get("AWS_REGION", "us-east-1")
        _s3 = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=f"https://s3.{region}.amazonaws.com",
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        )
    return _s3


def table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _table


def response(status: int, body: dict):
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def safe_filename(name: str) -> str:
    name = os.path.basename(name or "image")
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")
    return (name or "image")[:100]


def handler(event, _context):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return response(400, {"message": "Body must be JSON"})

    content_type = body.get("contentType", "")
    if content_type not in ALLOWED_TYPES:
        return response(400, {"message": f"contentType must be one of {sorted(ALLOWED_TYPES)}"})

    max_bytes = int(os.environ.get("MAX_UPLOAD_BYTES", 10_000_000))
    image_id = uuid.uuid4().hex
    filename = safe_filename(body.get("filename"))
    key = f"uploads/{image_id}/{filename}"
    now = datetime.now(timezone.utc).isoformat()

    table().put_item(
        Item={
            "imageId": image_id,
            "status": "PENDING_UPLOAD",
            "originalFilename": filename,
            "contentType": content_type,
            "sourceKey": key,
            "createdAt": now,
            "updatedAt": now,
        }
    )

    post = s3_client().generate_presigned_post(
        Bucket=os.environ["SOURCE_BUCKET"],
        Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[{"Content-Type": content_type}, ["content-length-range", 1, max_bytes]],
        ExpiresIn=URL_TTL_SECONDS,
    )
    return response(201, {"imageId": image_id, "upload": post, "expiresIn": URL_TTL_SECONDS, "maxBytes": max_bytes})
