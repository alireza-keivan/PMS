"""Staff-facing WhatsApp inbox. Not to be confused with the webhook routes
under /api/ - those receive messages from the provider; this is where staff
read and reply to them.
"""

from django.urls import path

from apps.messaging import views

app_name = "messaging"

urlpatterns = [
    path("", views.ConversationListView.as_view(), name="inbox"),
    path("<int:pk>/", views.ConversationDetailView.as_view(), name="thread"),
    path("<int:pk>/reply/", views.SendReplyView.as_view(), name="reply"),
]
