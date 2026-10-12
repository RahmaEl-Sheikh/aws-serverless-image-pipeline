"""Parallel branch 3 - extract image properties and a safe subset of EXIF."""
import io

from common import log, read_object

# Keep camera/exposure info; deliberately drop GPS and serial numbers (privacy).
EXIF_ALLOWLIST = {
    "Make", "Model", "LensModel", "DateTimeOriginal", "DateTime", "ExposureTime",
    "FNumber", "ISOSpeedRatings", "FocalLength", "Orientation", "Software",
}


def _clean(value):
    if isinstance(value, bytes):
        return value.decode(errors="ignore").strip("\x00")[:100]
    if isinstance(value, tuple):
        return [_clean(v) for v in value]
    if isinstance(value, (int, str)):
        return value
    try:
        return round(float(value), 4)  # IFDRational and friends
    except (TypeError, ValueError):
        return str(value)[:100]


def handler(event, _context):
    from PIL import ExifTags, Image

    data = read_object(event["bucket"], event["key"])
    with Image.open(io.BytesIO(data)) as image:
        exif = {}
        raw = image.getexif()
        merged = dict(raw)
        merged.update(raw.get_ifd(ExifTags.IFD.Exif))
        for tag_id, value in merged.items():
            name = ExifTags.TAGS.get(tag_id)
            if name in EXIF_ALLOWLIST:
                exif[name] = _clean(value)

        result = {
            "format": image.format,
            "mode": image.mode,
            "width": image.width,
            "height": image.height,
            "hasTransparency": image.mode in ("RGBA", "LA") or "transparency" in image.info,
            "animated": bool(getattr(image, "is_animated", False)),
            "hadGps": ExifTags.IFD.GPSInfo in raw,
            "exif": exif,
        }
    log("Metadata extracted", imageId=event["imageId"], fields=len(exif))
    return result
