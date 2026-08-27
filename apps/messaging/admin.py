from django.contrib import admin

from apps.messaging.models import Conversation, InboundMessage, MessageTemplate, OutboundMessage

admin.site.register(MessageTemplate)
admin.site.register(Conversation)


@admin.register(OutboundMessage)
class OutboundMessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "conversation", "status", "sent_at")
    list_filter = ("organization", "status")


@admin.register(InboundMessage)
class InboundMessageAdmin(admin.ModelAdmin):
    list_display = ("received_at", "conversation", "body")
    list_filter = ("organization",)
