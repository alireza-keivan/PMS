from django.urls import path

from apps.organizations import views

app_name = "organizations"

urlpatterns = [
    path("", views.StaffListView.as_view(), name="staff_list"),
    path("add/", views.StaffCreateView.as_view(), name="staff_add"),
    path("<int:pk>/villas/", views.StaffVillasView.as_view(), name="staff_villas"),
]
