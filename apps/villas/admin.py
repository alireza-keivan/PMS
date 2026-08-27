from django.contrib import admin

from apps.villas.models import Amenity, Villa, VillaPhoto


class VillaPhotoInline(admin.TabularInline):
    model = VillaPhoto
    extra = 0


@admin.register(Villa)
class VillaAdmin(admin.ModelAdmin):
    list_display = (
        "name", "organization", "property_type", "area", "bedrooms", "bathrooms",
        "max_guests", "is_listed_publicly", "is_active",
    )
    list_filter = ("organization", "property_type", "area", "is_active")
    inlines = [VillaPhotoInline]


@admin.register(Amenity)
class AmenityAdmin(admin.ModelAdmin):
    list_display = ("name_en", "name_id")
    filter_horizontal = ("villas",)
