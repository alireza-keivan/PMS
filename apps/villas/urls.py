from django.urls import path

from apps.villas.views import (
    RoomCategoryCreateView,
    RoomCategoryDeleteView,
    RoomCategoryUpdateView,
    RoomDeleteView,
    RoomQuickAddView,
    RoomRenameView,
    VillaCreateView,
    VillaDeleteView,
    VillaListView,
    VillaRenameView,
    VillaUpdateView,
)

app_name = "villas"

urlpatterns = [
    path("", VillaListView.as_view(), name="list"),
    path("add/", VillaCreateView.as_view(), name="add"),
    path("<slug:slug>/edit/", VillaUpdateView.as_view(), name="edit"),
    path("<slug:slug>/delete/", VillaDeleteView.as_view(), name="delete"),
    path("<slug:slug>/rename/", VillaRenameView.as_view(), name="rename"),
    path("<slug:slug>/rooms/quick-add/", RoomQuickAddView.as_view(), name="quick_add_room"),
    path("<slug:slug>/rooms/<int:pk>/remove/", RoomDeleteView.as_view(), name="remove_room"),
    path("<slug:slug>/rooms/<int:pk>/rename/", RoomRenameView.as_view(), name="rename_room"),
    path("<slug:slug>/room-types/add/", RoomCategoryCreateView.as_view(), name="add_room_category"),
    path(
        "<slug:slug>/room-types/<int:pk>/save/",
        RoomCategoryUpdateView.as_view(), name="save_room_category",
    ),
    path(
        "<slug:slug>/room-types/<int:pk>/remove/",
        RoomCategoryDeleteView.as_view(), name="remove_room_category",
    ),
    # path("<int:pk>/", views.VillaDetailView.as_view(), name="detail"),
]
