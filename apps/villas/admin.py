from django.contrib import admin

from apps.villas.models import Amenity, Villa, VillaPhoto


class VillaPhotoInline(admin.TabularInline):
    model = VillaPhoto
    extra = 0


@admin.register(Villa)
class VillaAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "area", "bedrooms", "is_listed_publicly", "is_active")
    list_filter = ("organization", "area", "is_active")
    inlines = [VillaPhotoInline]


admin.site.register(Amenity)
