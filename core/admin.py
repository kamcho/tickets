from django.contrib import admin
from .models import (
    Vendor,
    MyUser, TicketCategory, Ticket, TicketAssignment,
    TicketComments, TicketAttachments, AssistantConversation, AssistantMessage,
    NetworkRouter, CustomerHomeRouter,
)


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'email', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'slug', 'email')
    prepopulated_fields = {'slug': ('name',)}

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


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


@admin.register(MyUser)
class MyUserAdmin(admin.ModelAdmin):
    list_display = ('email', 'role', 'vendor', 'is_superuser', 'is_active')
    list_filter = ('role', 'vendor', 'is_superuser')
    search_fields = ('email', 'first_name', 'last_name', 'phone')
    raw_id_fields = ('vendor',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if getattr(request.user, 'vendor_id', None):
            return qs.filter(vendor_id=request.user.vendor_id)
        return qs.none()
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

