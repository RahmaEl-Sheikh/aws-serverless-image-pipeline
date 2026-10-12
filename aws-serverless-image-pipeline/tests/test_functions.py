"""Local unit tests - AWS is mocked with moto, images are generated with Pillow."""
import io
import json
import os
import sys

import boto3
import pytest
from moto import mock_aws
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "functions"))

REGION = "us-east-1"
SRC, DEST, TABLE = "pipeline-source-123", "pipeline-processed", "images"
IMAGE_ID = "0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    for k, v in {
        "AWS_DEFAULT_REGION": REGION, "AWS_REGION": REGION, "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test", "DEST_BUCKET": DEST, "SOURCE_BUCKET": SRC, "TABLE_NAME": TABLE,
    }.items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=SRC)
        s3.create_bucket(Bucket=DEST)
        boto3.client("dynamodb", region_name=REGION).create_table(
            TableName=TABLE, BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": n, "AttributeType": "S"} for n in ("imageId", "status", "createdAt")],
            KeySchema=[{"AttributeName": "imageId", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[{
                "IndexName": "byStatus", "Projection": {"ProjectionType": "ALL"},
                "KeySchema": [{"AttributeName": "status", "KeyType": "HASH"}, {"AttributeName": "createdAt", "KeyType": "RANGE"}],
            }],
        )
        # reset cached clients between tests
        for mod in ("common", "presign", "images_api", "dispatcher"):
            if mod in sys.modules:
                for attr in ("_s3", "_table", "_sfn"):
                    if hasattr(sys.modules[mod], attr):
                        setattr(sys.modules[mod], attr, None)
        yield s3


def put_image(s3, key, size=(2400, 1600), fmt="PNG", mode="RGBA"):
    buf = io.BytesIO()
    Image.new(mode, size, (30, 120, 200, 255) if mode == "RGBA" else (30, 120, 200)).save(buf, format=fmt)
    s3.put_object(Bucket=SRC, Key=key, Body=buf.getvalue())
    return {"imageId": IMAGE_ID, "bucket": SRC, "key": key}


def get_image(s3, key):
    return Image.open(io.BytesIO(s3.get_object(Bucket=DEST, Key=key)["Body"].read()))


def test_validate_accepts_image(aws_env):
    import validate
    result = validate.handler(put_image(aws_env, f"uploads/{IMAGE_ID}/a.png"), None)
    assert result["format"] == "PNG" and result["width"] == 2400 and result["height"] == 1600


def test_validate_rejects_non_image(aws_env):
    import validate
    from common import InvalidImageError
    aws_env.put_object(Bucket=SRC, Key=f"uploads/{IMAGE_ID}/x.png", Body=b"definitely not an image")
    with pytest.raises(InvalidImageError):
        validate.handler({"imageId": IMAGE_ID, "bucket": SRC, "key": f"uploads/{IMAGE_ID}/x.png"}, None)


def test_validate_rejects_oversized(aws_env, monkeypatch):
    import validate
    from common import InvalidImageError
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "100")
    with pytest.raises(InvalidImageError):
        validate.handler(put_image(aws_env, f"uploads/{IMAGE_ID}/a.png"), None)


def test_resize_creates_thumbnail(aws_env, monkeypatch):
    import resize
    monkeypatch.setenv("THUMBNAIL_SIZE", "320")
    result = resize.handler(put_image(aws_env, f"uploads/{IMAGE_ID}/a.png"), None)
    assert result["key"] == f"images/{IMAGE_ID}/thumbnail.jpg"
    img = get_image(aws_env, result["key"])
    assert img.format == "JPEG" and img.size == (320, 213)


def test_watermark_caps_size_and_changes_pixels(aws_env, monkeypatch):
    import watermark
    monkeypatch.setenv("FULL_RES_MAX_SIZE", "1600")
    result = watermark.handler(put_image(aws_env, f"uploads/{IMAGE_ID}/a.jpg", fmt="JPEG", mode="RGB"), None)
    img = get_image(aws_env, result["key"])
    assert img.size == (1600, 1067)
    # bottom-right corner (watermark area) differs from the plain top-left colour
    assert img.getpixel((1500, 1030)) != img.getpixel((10, 10))


def test_metadata_extracts_exif_without_gps(aws_env):
    import metadata
    img = Image.new("RGB", (640, 480), "red")
    exif = img.getexif()
    exif[0x010F] = "TestCam"      # Make
    exif[0x0110] = "Model X"      # Model
    exif[0x8825] = {2: (30.0, 2.0, 0.0)}  # GPSInfo
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    aws_env.put_object(Bucket=SRC, Key=f"uploads/{IMAGE_ID}/c.jpg", Body=buf.getvalue())

    result = metadata.handler({"imageId": IMAGE_ID, "bucket": SRC, "key": f"uploads/{IMAGE_ID}/c.jpg"}, None)
    assert result["exif"]["Make"] == "TestCam" and result["hadGps"] is True
    assert "GPSInfo" not in result["exif"]
    json.dumps(result)  # must be JSON-serialisable for Step Functions


def test_presign_returns_post_policy_and_records_item(aws_env):
    import presign
    resp = presign.handler({"body": json.dumps({"filename": "../My Photo!.png", "contentType": "image/png"})}, None)
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["upload"]["fields"]["key"] == f"uploads/{body['imageId']}/My-Photo-.png"
    item = boto3.resource("dynamodb", region_name=REGION).Table(TABLE).get_item(Key={"imageId": body["imageId"]})["Item"]
    assert item["status"] == "PENDING_UPLOAD"


def test_presign_rejects_bad_content_type(aws_env):
    import presign
    resp = presign.handler({"body": json.dumps({"filename": "x.exe", "contentType": "application/x-msdownload"})}, None)
    assert resp["statusCode"] == 400


def test_images_api_lists_completed_newest_first(aws_env):
    import images_api
    t = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    t.put_item(Item={"imageId": "a", "status": "COMPLETED", "createdAt": "2026-01-01", "width": 10, "metadata": "{}"})
    t.put_item(Item={"imageId": "b", "status": "COMPLETED", "createdAt": "2026-02-01", "width": 10, "metadata": "{}"})
    t.put_item(Item={"imageId": "c", "status": "FAILED", "createdAt": "2026-03-01"})
    body = json.loads(images_api.handler({}, None)["body"])
    assert [i["imageId"] for i in body["items"]] == ["b", "a"]
    assert images_api.handler({"pathParameters": {"imageId": "zzz"}}, None)["statusCode"] == 404


def test_dispatcher_starts_execution_and_is_idempotent(aws_env, monkeypatch):
    import dispatcher
    sfn = boto3.client("stepfunctions", region_name=REGION)
    role = "arn:aws:iam::123456789012:role/sfn"
    arn = sfn.create_state_machine(name="p", definition=json.dumps(
        {"StartAt": "x", "States": {"x": {"Type": "Pass", "End": True}}}), roleArn=role)["stateMachineArn"]
    monkeypatch.setenv("STATE_MACHINE_ARN", arn)

    s3_event = {"Records": [{"eventName": "ObjectCreated:Post", "s3": {
        "bucket": {"name": SRC}, "object": {"key": f"uploads/{IMAGE_ID}/My+Photo.png", "size": 5, "eTag": "e"}}}]}
    event = {"Records": [
        {"messageId": "m1", "body": json.dumps(s3_event)},
        {"messageId": "m2", "body": json.dumps(s3_event)},          # duplicate delivery
        {"messageId": "m3", "body": json.dumps({"Event": "s3:TestEvent"})},
        {"messageId": "m4", "body": "not json"},                     # poison message
    ]}
    result = dispatcher.handler(event, None)
    assert result == {"batchItemFailures": [{"itemIdentifier": "m4"}]}
    executions = sfn.list_executions(stateMachineArn=arn)["executions"]
    assert len(executions) == 1 and executions[0]["name"] == IMAGE_ID
    payload = json.loads(sfn.describe_execution(executionArn=executions[0]["executionArn"])["input"])
    assert payload["key"] == f"uploads/{IMAGE_ID}/My Photo.png"


def test_state_machine_definition_is_valid_json_with_all_states():
    path = os.path.join(os.path.dirname(__file__), "..", "statemachine", "pipeline.asl.json")
    definition = json.load(open(path))
    states = definition["States"]
    for name, state in states.items():
        for ref in [state.get("Next")] + [c["Next"] for c in state.get("Catch", [])]:
            assert ref is None or ref in states, f"{name} -> {ref} missing"
    assert definition["StartAt"] in states
