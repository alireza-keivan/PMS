from django.urls import path
from django.utils.translation import gettext_lazy as _

from apps.core.views import ComingSoonView

app_name = "compliance"

urlpatterns = [
    path("", ComingSoonView.as_view(extra_context={"title": _("Compliance")}), name="action_needed"),
    # path("documents/", views.DocumentListView.as_view(), name="documents"),
]
