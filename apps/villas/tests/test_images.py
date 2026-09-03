"""The picture pipeline: one shape and a sensible set of widths.

Operators upload photos in whatever shape their phone or their photographer
handed them. These tests pin the two things that turns into on a villa page -
every display copy is the same shape, and the widths on offer are the ones the
layouts actually ask for.
"""

from io import BytesIO

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image

from apps.villas.images import (
    DISPLAY_RATIO,
    RESPONSIVE_WIDTHS,
    _variant_name,
    center_crop,
    chosen_crop,
    responsive_srcset,
    webp_variant,
)


def _image(size):
    return Image.new("RGB", size, color=(120, 160, 150))


@pytest.mark.parametrize("size", [(2000, 500), (800, 2000), (1000, 1000), (1600, 900)])
def test_cropping_always_lands_on_the_wanted_shape(size):
    cropped = center_crop(_image(size), DISPLAY_RATIO)
    wanted = DISPLAY_RATIO[0] / DISPLAY_RATIO[1]

    # Rounding to whole pixels means "exactly 16:9" is not achievable for
    # every source, so allow a pixel's worth of slack rather than none.
    assert abs(cropped.width / cropped.height - wanted) < 0.01


def test_cropping_only_ever_removes_pixels():
    """No stretching and no padding - the fix is a trim, not a resize."""
    source = _image((800, 2000))
    cropped = center_crop(source, DISPLAY_RATIO)

    assert cropped.width <= source.width
    assert cropped.height <= source.height


def test_cropping_keeps_the_middle():
    """A tall picture loses its top and bottom evenly, not just its bottom.

    Villa photos are framed with the subject in the middle, so an even trim is
    the one that keeps the pool in the picture.
    """
    source = Image.new("RGB", (900, 1600), "white")
    for y in range(600):  # a dark band across the very middle
        for x in range(0, 900, 100):
            source.putpixel((x, 500 + y), (0, 0, 0))

    cropped = center_crop(source, DISPLAY_RATIO)

    assert cropped.getpixel((0, cropped.height // 2)) == (0, 0, 0)


class _Field:
    """Just enough of an ImageField for the resizing helpers."""

    storage = default_storage

    def __init__(self, name):
        self.name = name

    @property
    def url(self):
        return default_storage.url(self.name)


@pytest.fixture
def stored_photo():
    """A tall picture on disk, the awkward shape worth testing against."""
    buffer = BytesIO()
    _image((1800, 2400)).save(buffer, format="WEBP")
    name = default_storage.save("test-photos/tall.webp", ContentFile(buffer.getvalue()))
    yield _Field(name)
    for made in (name, *(
        _variant_name(name, width, ratio)
        for width in RESPONSIVE_WIDTHS
        for ratio in (None, DISPLAY_RATIO)
    )):
        default_storage.delete(made)


def test_a_display_copy_comes_out_at_the_asked_for_width_and_shape(stored_photo):
    webp_variant(stored_photo, 960, DISPLAY_RATIO)

    with default_storage.open(
        _variant_name(stored_photo.name, 960, DISPLAY_RATIO), "rb"
    ) as f:
        made = Image.open(f)
        made.load()

    assert made.width == 960
    assert made.height == 540
    assert made.format == "WEBP"


def test_a_cropped_copy_does_not_overwrite_the_uncropped_one(stored_photo):
    """Both live side by side - the ratio is part of the file name, so asking
    for one shape never hands back a file made for another."""
    plain = webp_variant(stored_photo, 960)
    cropped = webp_variant(stored_photo, 960, DISPLAY_RATIO)

    assert plain != cropped


def test_the_srcset_offers_a_step_between_the_gallery_thumb_and_the_hero():
    """1280 exists so a 340px-wide thumb on a 3x phone screen (about 1020px)
    stops jumping all the way to the 1600px hero file. That is real mobile
    data saved, which is the point of the whole set."""
    assert 1280 in RESPONSIVE_WIDTHS
    assert list(RESPONSIVE_WIDTHS) == sorted(RESPONSIVE_WIDTHS)


def test_every_srcset_entry_is_the_same_shape(stored_photo):
    srcset = responsive_srcset(stored_photo, DISPLAY_RATIO)

    assert len(srcset.split(", ")) == len(RESPONSIVE_WIDTHS)
    for width in RESPONSIVE_WIDTHS:
        assert f" {width}w" in srcset


# ---------------------------------------------------------------------------
# The frame the operator chose
# ---------------------------------------------------------------------------


def test_a_chosen_frame_keeps_the_part_the_operator_lined_up():
    """The whole reason the framing window exists: the top of a tall photo can
    be kept instead of the middle."""
    source = _image((1000, 2000))
    # The top third, at the wanted shape.
    kept = chosen_crop(source, (0.0, 0.0, 1.0, 0.28125), DISPLAY_RATIO)

    # The full width of the picture, give or take the pixel that rounding the
    # box back onto 16:9 can cost.
    assert kept.width >= 995
    assert kept.height < 600  # a slice off the top, not the whole 2000px
    assert abs(kept.width / kept.height - DISPLAY_RATIO[0] / DISPLAY_RATIO[1]) < 0.01


def test_a_chosen_frame_never_reaches_outside_the_picture():
    """The numbers come from a browser, so a box running off the edge has to
    be survivable - Pillow raising inside a guest's page request is not."""
    source = _image((1200, 800))
    kept = chosen_crop(source, (0.9, 0.9, 0.5, 0.5), DISPLAY_RATIO)

    assert kept.width <= 1200 and kept.height <= 800
    assert kept.width > 0 and kept.height > 0


def test_moving_the_frame_asks_for_a_different_file(stored_photo):
    """Otherwise a re-framed picture would keep showing its old framing for
    ever, because the copy already sitting in storage would still match."""
    first = webp_variant(stored_photo, 960, DISPLAY_RATIO, (0.0, 0.0, 1.0, 0.5))
    second = webp_variant(stored_photo, 960, DISPLAY_RATIO, (0.0, 0.4, 1.0, 0.5))
    middle = webp_variant(stored_photo, 960, DISPLAY_RATIO)

    assert first != second != middle
    for url in (first, second):
        default_storage.delete(url.split("/media/")[-1] if "/media/" in url else url)
