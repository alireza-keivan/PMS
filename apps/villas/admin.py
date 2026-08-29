from django.contrib import admin

from apps.villas.models import Amenity, Room, RoomCategory, Villa, VillaPhoto


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


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("name", "villa", "category", "is_active")
    # Room types are per villa now, so filtering by them across every operator
    # would list hundreds of near-duplicate names - filter by villa instead.
    list_filter = ("organization", "villa", "is_active")


@admin.register(RoomCategory)
class RoomCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "villa", "sort_order")
    list_filter = ("organization", "villa")


@admin.register(Amenity)
class AmenityAdmin(admin.ModelAdmin):
    list_display = ("name_en", "name_id")
    filter_horizontal = ("villas",)
