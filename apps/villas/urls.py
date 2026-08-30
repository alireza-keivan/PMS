from django.urls import path

from apps.villas.views import (
    AmenityCreateView,
    RoomAddView,
    RoomCategoryCreateView,
    RoomCategoryDeleteView,
    RoomDeleteView,
    RoomPhotoDeleteView,
    RoomPhotoUploadView,
    RoomQuickAddView,
    RoomRenameView,
    VillaDeleteView,
    VillaDetailsView,
    VillaListView,
    VillaPhotoDeleteView,
    VillaPhotoUploadView,
    VillaRenameView,
    VillaRoomsView,
    VillaUpdateView,
)

app_name = "villas"

urlpatterns = [
    path("", VillaListView.as_view(), name="list"),

    # Adding a villa, in two steps. Step 1 saves a draft and hands over to
    # step 2; going back to step 1 on a draft is the same view with a slug.
    path("add/", VillaDetailsView.as_view(), name="add"),
    path("add/<slug:slug>/", VillaDetailsView.as_view(), name="add_details"),

    path("<slug:slug>/edit/", VillaUpdateView.as_view(), name="edit"),
    path("<slug:slug>/delete/", VillaDeleteView.as_view(), name="delete"),
    path("<slug:slug>/rename/", VillaRenameView.as_view(), name="rename"),
    path("<slug:slug>/photos/add/", VillaPhotoUploadView.as_view(), name="add_villa_photos"),
    path("<slug:slug>/photos/<int:pk>/remove/", VillaPhotoDeleteView.as_view(), name="remove_villa_photo"),

    # The room blocks: step 2 while the villa is a draft, and the lower half
    # of the edit page once it is real.
    path("<slug:slug>/rooms/", VillaRoomsView.as_view(), name="rooms"),
    path("<slug:slug>/rooms/quick-add/", RoomQuickAddView.as_view(), name="quick_add_room"),
    # The calendar's "+ Add room": adds straight away when the villa only has
    # one room type, otherwise the card in _calendar_panel.html asks which
    # type first and posts here with category_id set.
    # quick_add_room/RoomQuickAddView is no longer called from anywhere in
    # the UI as of this change - left in place rather than removed, since
    # deleting it is out of scope here.
    path("<slug:slug>/rooms/add/", RoomAddView.as_view(), name="add_room"),
    path("<slug:slug>/rooms/<int:pk>/remove/", RoomDeleteView.as_view(), name="remove_room"),
    path("<slug:slug>/rooms/<int:pk>/rename/", RoomRenameView.as_view(), name="rename_room"),

    path("<slug:slug>/room-types/add/", RoomCategoryCreateView.as_view(), name="add_room_category"),
    path(
        "<slug:slug>/room-types/<int:pk>/remove/",
        RoomCategoryDeleteView.as_view(), name="remove_room_category",
    ),
    path(
        "<slug:slug>/room-types/<int:pk>/photos/",
        RoomPhotoUploadView.as_view(), name="add_room_photos",
    ),
    path(
        "<slug:slug>/room-types/<int:pk>/photos/<int:photo_pk>/remove/",
        RoomPhotoDeleteView.as_view(), name="remove_room_photo",
    ),

    path("amenities/add/", AmenityCreateView.as_view(), name="add_amenity"),
]
