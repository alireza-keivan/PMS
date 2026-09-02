"""Photo processing.

Every guest-facing image is served as WebP. If Pillow cannot produce WebP for a
given source, this raises rather than writing a JPEG or PNG instead - a silent
format fallback would quietly undo the page-weight decision. See CLAUDE.md.
"""

import logging
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, features

logger = logging.getLogger(__name__)


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


# The widths the public villa pages offer in `srcset`. Chosen against the
# layouts in the design, not picked round: 480 covers a phone's full-bleed
# cover photo at 1x and a room card at 2x, 960 a phone cover at 2x and the
# desktop room grid, 1600 the desktop hero. Anything wider is the original.
RESPONSIVE_WIDTHS = (480, 960, 1600)


def _variant_name(name: str, width: int) -> str:
    return f"{name.rsplit('.', 1)[0]}-{width}w.webp"


def webp_variant(image_field, width: int) -> str:
    """URL for `image_field` resized to `width` px wide, made once and kept.

    Guests open these pages on a phone over Indonesian mobile data, so the
    cover photo must not arrive as the 2000px original. The resize happens on
    the first request that needs it and is written next to the source file, so
    every later request - and every other visitor - is served straight from
    storage with no work at all.

    Still WebP, never anything else: this narrows an image that to_webp()
    already converted on upload. If the resize itself fails (a file missing
    from storage, say) the original's own URL is returned - the same picture,
    just not shrunk. That is not a format fallback, and the WebP-only rule in
    to_webp() stands untouched.
    """
    storage = image_field.storage
    target = _variant_name(image_field.name, width)

    try:
        if not storage.exists(target):
            with storage.open(image_field.name, "rb") as source:
                image = Image.open(source)
                image.load()
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGB")
            if image.width > width:
                ratio = width / image.width
                image = image.resize((width, round(image.height * ratio)), Image.LANCZOS)
            buffer = BytesIO()
            image.save(buffer, format="WEBP", quality=settings.IMAGE_WEBP_QUALITY, method=6)
            storage.save(target, ContentFile(buffer.getvalue()))
        return storage.url(target)
    except Exception:
        logger.warning("Could not build a %spx copy of %s", width, image_field.name, exc_info=True)
        return image_field.url


def responsive_srcset(image_field) -> str:
    """A `srcset` value listing every width in RESPONSIVE_WIDTHS.

    Paired with a `sizes` attribute in the template, this lets the browser
    pick before it downloads anything - which is the whole point on 4G.
    """
    return ", ".join(
        f"{webp_variant(image_field, width)} {width}w" for width in RESPONSIVE_WIDTHS
    )
