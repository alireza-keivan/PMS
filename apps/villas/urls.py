from django.urls import path

from apps.villas.views import VillaCreateView, VillaDeleteView, VillaListView, VillaUpdateView

app_name = "villas"

urlpatterns = [
    path("", VillaListView.as_view(), name="list"),
    path("add/", VillaCreateView.as_view(), name="add"),
    path("<slug:slug>/edit/", VillaUpdateView.as_view(), name="edit"),
    path("<slug:slug>/delete/", VillaDeleteView.as_view(), name="delete"),
    # path("<int:pk>/", views.VillaDetailView.as_view(), name="detail"),
]
