from django.contrib import admin

from apps.messaging.models import Conversation, MessageTemplate, OutboundMessage

admin.site.register(MessageTemplate)
admin.site.register(Conversation)


@admin.register(OutboundMessage)
class OutboundMessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "conversation", "status", "sent_at")
    list_filter = ("organization", "status")
