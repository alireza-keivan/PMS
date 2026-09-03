"""Showing a picture on the villa form the way a guest will see it.

The form's picture row used to show square thumbnails of the whole upload,
which is not what the villa page shows - that page cuts every picture to
16:9. So an operator lined a photo up in their head against a square box and
then found the top of it missing on the real page. These tags draw the row
using the very same crop the public page uses, so the row is a true preview.
"""

from django import template

from apps.villas.images import DISPLAY_RATIO, webp_variant

register = template.Library()

# Big enough for the form's thumbnails on a 3x phone screen, small enough that
# building one costs nothing noticeable while somebody is uploading.
FORM_THUMB_WIDTH = 480


@register.simple_tag
def photo_thumb(photo):
    """The picture as the villa page will show it - 16:9, with its own crop."""
    return webp_variant(photo.image, FORM_THUMB_WIDTH, DISPLAY_RATIO, photo.crop)


@register.simple_tag
def display_ratio_css():
    """The frame's shape, for a CSS `aspect-ratio` - one place decides it."""
    return f"{DISPLAY_RATIO[0]} / {DISPLAY_RATIO[1]}"
