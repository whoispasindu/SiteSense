"""Turns an untrusted upload into a safe site photo.

The client's file name and content type are ignored. The bytes must start with a JPEG, PNG or
WebP signature, decode fully, and stay under a pixel budget (decompression bombs). The image is
then re-encoded from pixels to a fresh JPEG: EXIF (including GPS position), comments and any
appended payload are dropped, and the stored file is always a plain image.
"""

import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import BusinessRuleError

MAX_PIXELS = 50_000_000  # about 8,000 x 6,000: above any phone camera
MAX_EDGE = 2560  # stored size, plenty for reading a site photo
THUMB_EDGE = 480

_SIGNATURES: tuple[tuple[str, bytes, int], ...] = (
    ("JPEG", b"\xff\xd8\xff", 0),
    ("PNG", b"\x89PNG\r\n\x1a\n", 0),
    ("WEBP", b"WEBP", 8),
)


class PhotoRejectedError(BusinessRuleError):
    code = "photo_rejected"


@dataclass(frozen=True, slots=True)
class ProcessedPhoto:
    full: bytes
    thumb: bytes
    width: int
    height: int


def sniff_format(data: bytes) -> str | None:
    """The image format from the file's magic bytes, or None if it is not a supported image."""
    for name, signature, offset in _SIGNATURES:
        if data[offset : offset + len(signature)] == signature:
            if name == "WEBP" and data[:4] != b"RIFF":
                continue
            return name
    return None


def _encode(image: Image.Image, edge: int, quality: int) -> bytes:
    copy = image.copy()
    copy.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    # No exif/icc arguments: Pillow writes none, so no metadata survives.
    copy.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def process(data: bytes) -> ProcessedPhoto:
    expected = sniff_format(data)
    if expected is None:
        raise PhotoRejectedError("Only JPEG, PNG or WebP photos can be uploaded.")
    try:
        with warnings.catch_warnings():
            # Treat "suspiciously large" as an error instead of a warning.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                if probe.format != expected:
                    raise PhotoRejectedError("The file content does not match a supported image type.")
                if probe.width * probe.height > MAX_PIXELS:
                    raise PhotoRejectedError("The photo has too many pixels.")
                probe.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                upright = ImageOps.exif_transpose(image)
                rgb = upright.convert("RGB")
    except PhotoRejectedError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise PhotoRejectedError("The photo could not be read.") from exc
    except (OSError, SyntaxError, ValueError) as exc:  # truncated or corrupt data
        raise PhotoRejectedError("The photo could not be read.") from exc

    full = _encode(rgb, MAX_EDGE, quality=85)
    with Image.open(io.BytesIO(full)) as stored:
        width, height = stored.size
    return ProcessedPhoto(full=full, thumb=_encode(rgb, THUMB_EDGE, quality=75), width=width, height=height)
