"""Step 1 - validate the uploaded object before spending compute on it."""
import io
import os

from common import SUPPORTED_FORMATS, InvalidImageError, log, s3_client

MAX_PIXELS = 50_000_000  # guards against decompression bombs


def handler(event, _context):
    bucket, key = event["bucket"], event["key"]
    max_bytes = int(os.environ.get("MAX_UPLOAD_BYTES", 10_000_000))

    head = s3_client().head_object(Bucket=bucket, Key=key)
    size = head["ContentLength"]
    if size == 0:
        raise InvalidImageError("Uploaded file is empty")
    if size > max_bytes:
        raise InvalidImageError(f"File is {size} bytes; limit is {max_bytes}")

    from PIL import Image, UnidentifiedImageError

    data = s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt, width, height = probe.format, probe.width, probe.height
            probe.verify()  # detects truncated / corrupted files
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise InvalidImageError(f"Not a readable image: {exc}") from exc

    if fmt not in SUPPORTED_FORMATS:
        raise InvalidImageError(f"Unsupported format {fmt}; allowed: {sorted(SUPPORTED_FORMATS)}")
    if width * height > MAX_PIXELS:
        raise InvalidImageError(f"Image is {width}x{height}; exceeds {MAX_PIXELS} pixels")

    result = {"format": fmt, "width": width, "height": height, "sizeBytes": size}
    log("Image validated", imageId=event["imageId"], **result)
    return result
