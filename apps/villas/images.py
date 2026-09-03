"""Photo processing.

Every guest-facing image is served as WebP. If Pillow cannot produce WebP for a
given source, this raises rather than writing a JPEG or PNG instead - a silent
format fallback would quietly undo the page-weight decision. See CLAUDE.md.
"""

import logging
import time
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
# desktop room grid, 1280 a gallery thumb or room card on a 3x phone screen,
# 1600 the desktop hero. Anything wider is the original.
#
# 1280 earns its place: the gallery thumbs are 340px wide, so a phone at 3x
# asks for about 1020px. Without this step the browser jumped straight to the
# 1600px file and spent data nobody could see - which matters on Indonesian
# mobile.
RESPONSIVE_WIDTHS = (480, 960, 1280, 1600)

# The shape every guest-facing copy is cropped to. Operators upload whatever
# their phone or their photographer gave them - tall, square, panoramic - and
# a strip of pictures in mixed shapes looks broken however carefully the boxes
# are sized. One shape for all of them makes the page look deliberate, and it
# is close enough to every box on the villa page that the extra trimming the
# browser does on top is small.
DISPLAY_RATIO = (16, 9)


def _ratio_tag(ratio) -> str:
    return "" if ratio is None else f"-{ratio[0]}x{ratio[1]}"


def _crop_tag(crop) -> str:
    """A short stamp of the chosen box, for the copy's file name.

    Without it, moving the box would leave the old copy sitting in storage
    under the same name and the villa page would keep showing the old framing
    for ever. With it, a moved box simply asks for a file that isn't there
    yet, and the next request builds it.
    """
    if crop is None:
        return ""
    return "-c" + "".join(f"{round(value * 1000):04d}" for value in crop)


def cropped_size(image_field, ratio=None, crop=None):
    """How many pixels the finished copy really has, before any resizing.

    Needed because nothing is ever enlarged: a crop taken from the middle of
    an already-shrunk upload can easily be narrower than the widths in
    RESPONSIVE_WIDTHS, and telling the browser a 1250px file is 1600px wide
    only gets it stretched back up on the page. See responsive_srcset().
    """
    width, height = image_field.width, image_field.height
    if crop is not None:
        width = max(1, round(crop[2] * width))
        height = max(1, round(crop[3] * height))
    if ratio is not None:
        wanted = ratio[0] / ratio[1]
        if width / height > wanted:
            width = round(height * wanted)
    return width


def _variant_name(name: str, width: int, ratio=None, crop=None) -> str:
    return f"{name.rsplit('.', 1)[0]}-{width}w{_ratio_tag(ratio)}{_crop_tag(crop)}.webp"


def center_crop(image, ratio):
    """Trim `image` to `ratio` (a (w, h) pair), keeping the middle.

    Only ever removes pixels - the crop takes the largest box of that shape
    that still fits inside the picture, so nothing is stretched and nothing is
    padded. Centre is the right default guess: villa photos are framed with
    the subject in the middle far more often than not.
    """
    wanted = ratio[0] / ratio[1]
    if image.width / image.height > wanted:
        # Too wide - take height in full, trim the sides.
        new_width, new_height = round(image.height * wanted), image.height
    else:
        # Too tall - take width in full, trim top and bottom.
        new_width, new_height = image.width, round(image.width / wanted)
    left = (image.width - new_width) // 2
    top = (image.height - new_height) // 2
    return image.crop((left, top, left + new_width, top + new_height))


def chosen_crop(image, crop, ratio):
    """Cut `image` down to the box the operator lined up, as fractions.

    `crop` is (x, y, width, height), each a fraction of the whole picture. The
    result is nudged back onto `ratio` afterwards - the browser widget already
    works in that shape, but rounding to whole pixels can leave it a pixel
    out, and a page of pictures that are each a pixel different in shape is
    the untidiness DISPLAY_RATIO exists to stop.
    """
    x, y, width, height = crop
    left = round(x * image.width)
    top = round(y * image.height)
    right = min(image.width, left + max(1, round(width * image.width)))
    bottom = min(image.height, top + max(1, round(height * image.height)))
    box = image.crop((left, top, right, bottom))
    return center_crop(box, ratio) if ratio else box


def webp_variant(image_field, width: int, ratio=None, crop=None) -> str:
    """URL for `image_field` resized to `width` px wide, made once and kept.

    With `ratio` given as a (w, h) pair the copy is also cropped to that shape
    first - to the box the operator chose when they uploaded it if there is
    one (`crop`), and otherwise to the middle of the picture. Either way every
    picture on a page arrives already the same shape, rather than relying on
    the browser to hide the difference.

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
    target = _variant_name(image_field.name, width, ratio, crop)

    try:
        if not storage.exists(target):
            # Logged at every step: this runs lazily on the first guest request
            # that needs the copy, so without a trace there is no way to tell
            # from the log whether it ran, how big the result was, or how much
            # of the page's time it took.
            started = time.monotonic()
            with storage.open(image_field.name, "rb") as source:
                image = Image.open(source)
                image.load()
            source_size = image.size
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGB")
            if crop is not None:
                image = chosen_crop(image, crop, ratio)
            elif ratio is not None:
                image = center_crop(image, ratio)
            if image.width > width:
                # Not named `ratio`: that argument is the wanted shape, and
                # reusing the name for a scale factor here would be a trap for
                # anyone adding a line below this one.
                scale = width / image.width
                image = image.resize((width, round(image.height * scale)), Image.LANCZOS)
            buffer = BytesIO()
            image.save(buffer, format="WEBP", quality=settings.IMAGE_WEBP_QUALITY, method=6)
            storage.save(target, ContentFile(buffer.getvalue()))
            logger.info(
                "Built display copy %s - from %sx%s to %sx%s, shape %s, %s KB, %.0f ms",
                target, source_size[0], source_size[1], image.width, image.height,
                f"{ratio[0]}x{ratio[1]}{' chosen' if crop else ''}" if ratio else "uncropped",
                round(buffer.tell() / 1024), (time.monotonic() - started) * 1000,
            )
        return storage.url(target)
    except Exception:
        logger.warning("Could not build a %spx copy of %s", width, image_field.name, exc_info=True)
        return image_field.url


def responsive_srcset(image_field, ratio=None, crop=None) -> str:
    """A `srcset` value listing every width in RESPONSIVE_WIDTHS.

    Paired with a `sizes` attribute in the template, this lets the browser
    pick before it downloads anything - which is the whole point on 4G. Every
    entry is cropped to the same `ratio`, so switching between them as the
    screen changes never changes what the picture shows.
    """
    try:
        available = cropped_size(image_field, ratio, crop)
    except Exception:
        logger.warning("Could not measure %s", image_field.name, exc_info=True)
        available = RESPONSIVE_WIDTHS[-1]

    # Only widths the crop can actually fill, plus the crop's own width as the
    # top entry. Without this the last entries are all the same file under
    # bigger and bigger labels, and the browser picks the biggest label.
    widths = [w for w in RESPONSIVE_WIDTHS if w < available]
    widths.append(available)
    return ", ".join(
        f"{webp_variant(image_field, width, ratio, crop)} {width}w"
        for width in widths
    )
