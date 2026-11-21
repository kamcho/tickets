from django.contrib import admin

from billing.models import (
    Expenditure, Invoice, MpesaPayment, NetworkServiceAccount, Plan, Subscription,
)


@admin.register(MpesaPayment)
class MpesaPaymentAdmin(admin.ModelAdmin):
    list_display = (
        'payment_id', 'source', 'phone', 'amount', 'status', 'mpesa_receipt_number',
        'customer', 'created_at', 'completed_at',
    )
    list_filter = ('status', 'source')
    search_fields = (
        'payment_id', 'phone', 'mpesa_receipt_number',
        'checkout_request_id', 'merchant_request_id',
        'originator_conversation_id', 'account_reference',
    )
    readonly_fields = (
        'payment_id', 'merchant_request_id', 'checkout_request_id',
        'originator_conversation_id', 'mpesa_receipt_number',
        'raw_stk_response', 'raw_callback',
        'created_at', 'updated_at', 'completed_at', 'billing_applied_at',
    )
    raw_id_fields = ('customer', 'initiated_by', 'invoice', 'subscription')


@admin.register(NetworkServiceAccount)
class NetworkServiceAccountAdmin(admin.ModelAdmin):
    list_display = (
        'username', 'customer', 'router', 'profile', 'disabled',
        'last_synced_at', 'last_error',
    )
    list_filter = ('disabled', 'router')
    search_fields = ('username', 'customer__phone', 'customer__email', 'customer__first_name')
    raw_id_fields = ('customer', 'router')
    readonly_fields = ('last_synced_at', 'created_at', 'updated_at')


@admin.register(Expenditure)
class ExpenditureAdmin(admin.ModelAdmin):
    list_display = ('title', 'amount', 'payment_method', 'occurred_at', 'created_at')
    list_filter = ('payment_method',)
    search_fields = ('title', 'description')
    date_hierarchy = 'occurred_at'
    ordering = ('-occurred_at',)


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'speed_mbps', 'price', 'mikrotik_profile', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'mikrotik_profile')


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'plan', 'status', 'started_at', 'expires_at')
    list_filter = ('status', 'plan')
    search_fields = ('customer__email', 'customer__phone', 'customer__first_name')
    raw_id_fields = ('customer',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        'invoice_id', 'subscription', 'amount_due', 'amount_paid',
        'status', 'period_start', 'period_end', 'due_at',
    )
    list_filter = ('status',)
    search_fields = ('invoice_id', 'subscription__customer__email', 'subscription__customer__phone')
    raw_id_fields = ('subscription',)
    readonly_fields = ('invoice_id', 'created_at', 'updated_at')
