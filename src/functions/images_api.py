"""GET /images and GET /images/{imageId} - read side of the pipeline."""
import json
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

_table = None
PUBLIC_FIELDS = (
    "imageId", "status", "originalFilename", "createdAt", "updatedAt", "thumbnailKey",
    "fullResKey", "width", "height", "format", "sizeBytes", "metadata", "errorMessage",
)


def table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _table


def _json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(type(value))


def response(status: int, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(body, default=_json_default),
    }


def public_view(item: dict) -> dict:
    view = {k: item[k] for k in PUBLIC_FIELDS if k in item}
    if isinstance(view.get("metadata"), str):
        view["metadata"] = json.loads(view["metadata"])
    return view


def handler(event, _context):
    image_id = (event.get("pathParameters") or {}).get("imageId")
    if image_id:
        item = table().get_item(Key={"imageId": image_id}).get("Item")
        if not item:
            return response(404, {"message": "Image not found"})
        return response(200, public_view(item))

    params = event.get("queryStringParameters") or {}
    limit = max(1, min(int(params.get("limit", 24)), 100))
    result = table().query(
        IndexName="byStatus",
        KeyConditionExpression=Key("status").eq("COMPLETED"),
        ScanIndexForward=False,  # newest first
        Limit=limit,
    )
    return response(200, {"items": [public_view(i) for i in result.get("Items", [])]})
