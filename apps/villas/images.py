"""Photo processing.

Every guest-facing image is served as WebP. If Pillow cannot produce WebP for a
given source, this raises rather than writing a JPEG or PNG instead - a silent
format fallback would quietly undo the page-weight decision. See CLAUDE.md.
"""

from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, features


class WebPUnavailable(RuntimeError):
    """Pillow was built without WebP support."""


def to_webp(uploaded_file, max_width: int = 2000) -> ContentFile:
    if not features.check("webp"):
        raise WebPUnavailable(
            "Pillow has no WebP support in this environment. Install a Pillow "
            "build with libwebp, or move image handling to a CDN that outputs "
            "WebP - do not fall back to JPEG."
        )

    image = Image.open(uploaded_file)
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")
    if image.width > max_width:
        ratio = max_width / image.width
        image = image.resize((max_width, round(image.height * ratio)), Image.LANCZOS)

    buffer = BytesIO()
    image.save(buffer, format="WEBP", quality=settings.IMAGE_WEBP_QUALITY, method=6)
    name = uploaded_file.name.rsplit(".", 1)[0] + ".webp"
    return ContentFile(buffer.getvalue(), name=name)
