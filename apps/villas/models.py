"""Villas and their photos."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantOwnedModel


class Villa(TenantOwnedModel):
    name = models.CharField(max_length=160)
    slug = models.SlugField(help_text=_("Used in the villa's public web address."))
    area = models.CharField(
        max_length=80, blank=True, help_text=_("Canggu, Ubud, Uluwatu, Seminyak.")
    )
    address = models.TextField(blank=True)
    bedrooms = models.PositiveSmallIntegerField(default=1)
    max_guests = models.PositiveSmallIntegerField(default=2)

    # Bilingual free text. Kept as explicit per-language fields rather than
    # gettext because this is operator-authored content, not interface copy.
    description_en = models.TextField(blank=True)
    description_id = models.TextField(blank=True)

    is_listed_publicly = models.BooleanField(
        default=False, help_text=_("Show this villa's own web page and direct booking.")
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("organization", "slug")]

    def __str__(self):
        return self.name


class VillaPhoto(TenantOwnedModel):
    """Stored as WebP. Conversion happens on upload - see apps/villas/images.py."""

    villa = models.ForeignKey(Villa, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="villas/%Y/%m/")
    caption_en = models.CharField(max_length=200, blank=True)
    caption_id = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_cover = models.BooleanField(default=False)

    class Meta:
        ordering = ["sort_order", "id"]


class Amenity(models.Model):
    """Shared vocabulary across all operators, so it is not tenant-scoped."""

    name_en = models.CharField(max_length=80)
    name_id = models.CharField(max_length=80)
    icon = models.CharField(max_length=40, blank=True)
    villas = models.ManyToManyField(Villa, blank=True, related_name="amenities")

    class Meta:
        ordering = ["name_en"]
        verbose_name_plural = _("amenities")

    def __str__(self):
        return self.name_en
