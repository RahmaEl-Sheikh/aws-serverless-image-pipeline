"""Parallel branch 1 - create a thumbnail."""
import os

from common import log, open_image, read_object, save_jpeg, to_rgb


def handler(event, _context):
    size = int(os.environ.get("THUMBNAIL_SIZE", 320))
    image = to_rgb(open_image(read_object(event["bucket"], event["key"])))
    image.thumbnail((size, size))  # keeps aspect ratio, never upscales

    result = save_jpeg(image, os.environ["DEST_BUCKET"], f"images/{event['imageId']}/thumbnail.jpg", quality=80)
    log("Thumbnail created", imageId=event["imageId"], **result)
    return result
