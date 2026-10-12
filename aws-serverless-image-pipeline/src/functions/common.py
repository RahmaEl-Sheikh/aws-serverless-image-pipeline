"""Shared helpers for the image-processing Lambda functions."""
import io
import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_s3 = None

SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}


class InvalidImageError(Exception):
    """Raised for inputs that will never succeed - Step Functions routes this to REJECTED, no retries."""


def s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def read_object(bucket: str, key: str) -> bytes:
    return s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()


def open_image(data: bytes):
    """Open image bytes with Pillow, applying the EXIF orientation so photos aren't rotated."""
    from PIL import Image, ImageOps  # Pillow comes from the Lambda layer

    image = Image.open(io.BytesIO(data))
    image = ImageOps.exif_transpose(image)
    return image


def to_rgb(image):
    """Flatten transparency onto white so the result can be saved as JPEG."""
    from PIL import Image

    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def save_jpeg(image, bucket: str, key: str, quality: int = 85) -> dict:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
    body = buffer.getvalue()
    s3_client().put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="image/jpeg",
        CacheControl="public, max-age=31536000, immutable",
    )
    return {"key": key, "width": image.width, "height": image.height, "sizeBytes": len(body)}


def log(message: str, **fields):
    logger.info(json.dumps({"message": message, **fields}, default=str))
