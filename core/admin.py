from django.contrib import admin
from .models import (
    MyUser, TicketCategory, Ticket, TicketAssignment,
    TicketComments, TicketAttachments, AssistantConversation, AssistantMessage,
    NetworkRouter, CustomerHomeRouter,
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


@admin.register(CustomerHomeRouter)
class CustomerHomeRouterAdmin(admin.ModelAdmin):
    list_display = (
        'display_name', 'customer', 'serial_number', 'ownership',
        'installed_at', 'is_active',
    )
    list_filter = ('ownership', 'is_active', 'brand')
    search_fields = (
        'brand', 'model', 'serial_number', 'mac_address', 'ssid',
        'customer__first_name', 'customer__last_name', 'customer__phone',
    )
    raw_id_fields = ('customer',)


@admin.register(NetworkRouter)
class NetworkRouterAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'effective_api_host', 'is_default', 'status',
        'location', 'customers_served', 'is_active',
    )
    list_filter = ('status', 'is_active', 'is_default', 'api_ssl')
    search_fields = ('name', 'ip_address', 'api_host', 'location', 'notes')
    fieldsets = (
        (None, {
            'fields': (
                'name', 'location', 'status', 'customers_served',
                'is_active', 'is_default', 'notes', 'last_seen_at',
            ),
        }),
        ('MikroTik REST API', {
            'description': (
                'Credentials per router (preferred). '
                '.env MIKROTIK_* is only a single-router fallback.'
            ),
            'fields': (
                'ip_address', 'api_host', 'api_user', 'api_password',
                'api_ssl', 'api_verify_ssl', 'api_port',
            ),
        }),
    )

