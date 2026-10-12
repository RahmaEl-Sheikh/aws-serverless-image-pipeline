"""Parallel branch 2 - size-capped, watermarked full-resolution rendition.

Re-encoding through Pillow also strips the original EXIF block (including GPS)
from the publicly served image.
"""
import os

from common import log, open_image, read_object, save_jpeg, to_rgb


def apply_watermark(image, text: str):
    from PIL import Image, ImageDraw, ImageFont

    base = image.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = max(12, base.width // 45)
    font = ImageFont.load_default(size=font_size)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    text_w, text_h = right - left, bottom - top
    pad = max(4, font_size // 2)
    margin = max(8, base.width // 60)

    # badge box anchored to the bottom-right corner, text centred inside it
    x1, y1 = base.width - margin, base.height - margin
    x0, y0 = x1 - text_w - 2 * pad, y1 - text_h - 2 * pad
    draw.rounded_rectangle((x0, y0, x1, y1), radius=pad, fill=(0, 0, 0, 80))
    draw.text((x0 + pad - left, y0 + pad - top), text, font=font, fill=(255, 255, 255, 210))
    return Image.alpha_composite(base, overlay).convert("RGB")


def handler(event, _context):
    max_size = int(os.environ.get("FULL_RES_MAX_SIZE", 1600))
    text = os.environ.get("WATERMARK_TEXT", "(c) Image Pipeline")

    image = to_rgb(open_image(read_object(event["bucket"], event["key"])))
    image.thumbnail((max_size, max_size))
    image = apply_watermark(image, text)

    result = save_jpeg(image, os.environ["DEST_BUCKET"], f"images/{event['imageId']}/full.jpg", quality=88)
    log("Watermarked rendition created", imageId=event["imageId"], **result)
    return result
