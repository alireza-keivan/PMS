from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.villas.models import (
    Amenity,
    Room,
    RoomCategory,
    RoomCategoryPhoto,
    Villa,
    VillaPhoto,
)


class VillaPhotoInline(admin.TabularInline):
    model = VillaPhoto
    extra = 0


class RoomCategoryPhotoInline(admin.TabularInline):
    model = RoomCategoryPhoto
    extra = 0


@admin.register(Villa)
class VillaAdmin(admin.ModelAdmin):
    list_display = (
        "name", "organization", "property_type", "area", "bedrooms",
        "is_listed_publicly", "is_draft", "is_active",
    )
    # is_draft is filterable on purpose: an operator asking "where did my villa
    # go" is usually one who never finished adding it.
    list_filter = ("organization", "property_type", "area", "is_draft", "is_active")
    inlines = [VillaPhotoInline]


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("name", "villa", "category", "is_active")
    # Room types are per villa now, so filtering by them across every operator
    # would list hundreds of near-duplicate names - filter by villa instead.
    list_filter = ("organization", "villa", "is_active")


@admin.register(RoomCategory)
class RoomCategoryAdmin(admin.ModelAdmin):
    list_display = (
        "name", "villa", "room_count", "max_guests",
        "nightly_rate", "minimum_nights", "sort_order",
    )
    list_filter = ("organization", "villa")
    filter_horizontal = ("amenities",)
    inlines = [RoomCategoryPhotoInline]

    @admin.display(description=_("rooms"))
    def room_count(self, obj):
        return obj.rooms.count()


@admin.register(Amenity)
class AmenityAdmin(admin.ModelAdmin):
    # A blank organization means everyone gets it; a filled one means it is
    # one operator's own wording, offered only back to them.
    list_display = ("name_en", "name_id", "organization")
    list_filter = ("organization",)
    search_fields = ("name_en", "name_id")
