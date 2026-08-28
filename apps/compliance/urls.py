from django.urls import path

from apps.compliance import views

app_name = "compliance"

urlpatterns = [
    path("", views.ActionNeededView.as_view(), name="action_needed"),
    path("documents/", views.DocumentListView.as_view(), name="documents"),
    path("documents/add/", views.DocumentCreateView.as_view(), name="add_document"),
    path("police-reports/<int:pk>/done/", views.MarkPoliceReportDoneView.as_view(), name="mark_police_report_done"),
]
