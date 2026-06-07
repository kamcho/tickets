from django.contrib import admin
from .models import (
    MyUser, TicketCategory, Ticket, TicketAssignment,
    TicketComments, TicketAttachments, AssistantConversation, AssistantMessage,
)


class AssistantMessageInline(admin.TabularInline):
    model = AssistantMessage
    extra = 0
    readonly_fields = ('role', 'content', 'tool_name', 'created_at')


@admin.register(AssistantConversation)
class AssistantConversationAdmin(admin.ModelAdmin):
    list_display = ('channel', 'session_key', 'customer', 'whatsapp_phone', 'updated_at')
    list_filter = ('channel',)
    search_fields = ('session_key', 'whatsapp_phone')
    inlines = [AssistantMessageInline]


admin.site.register(MyUser)
admin.site.register(TicketCategory)
admin.site.register(Ticket)
admin.site.register(TicketAssignment)
admin.site.register(TicketComments)
admin.site.register(TicketAttachments)
