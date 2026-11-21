"""M-Pesa payment history and related billing models."""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


def _new_payment_id():
    return f'PAY-{uuid.uuid4().hex[:8].upper()}'


def _new_invoice_id():
    return f'INV-{uuid.uuid4().hex[:8].upper()}'


class MpesaPayment(models.Model):
    """One payment attempt (STK, pull-query, or manual) and its outcome."""

    STATUS_PENDING = 'pending'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = (
        (STATUS_PENDING, 'Pending'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_CANCELLED, 'Cancelled'),
    )

    SOURCE_STK = 'stk'
    SOURCE_PULL = 'pull'
    SOURCE_MANUAL = 'manual'
    SOURCE_CHOICES = (
        (SOURCE_STK, 'STK Push'),
        (SOURCE_PULL, 'Pull transaction'),
        (SOURCE_MANUAL, 'Manual record'),
    )

    payment_id = models.CharField(max_length=20, unique=True, default=_new_payment_id, editable=False)
    source = models.CharField(
        max_length=16,
        choices=SOURCE_CHOICES,
        default=SOURCE_STK,
        db_index=True,
        help_text='How this payment was captured.',
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mpesa_payments',
        limit_choices_to={'role': 'Customer'},
    )
    phone = models.CharField(max_length=15, help_text='254XXXXXXXXX used for STK Push')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    account_reference = models.CharField(max_length=64, help_text='Shown on M-Pesa prompt / statement')
    description = models.CharField(max_length=120, blank=True, default='')

    merchant_request_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    checkout_request_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    originator_conversation_id = models.CharField(
        max_length=64,
        blank=True,
        default='',
        db_index=True,
        help_text='Daraja OriginatorConversationID for async pull / transaction-status queries.',
    )
    mpesa_receipt_number = models.CharField(max_length=64, blank=True, default='', db_index=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    result_code = models.IntegerField(null=True, blank=True)
    result_desc = models.CharField(max_length=255, blank=True, default='')

    raw_stk_response = models.JSONField(default=dict, blank=True)
    raw_callback = models.JSONField(default=dict, blank=True)

    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mpesa_payments_initiated',
    )
    invoice = models.ForeignKey(
        'Invoice',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mpesa_payments',
    )
    subscription = models.ForeignKey(
        'Subscription',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mpesa_payments',
    )
    billing_applied_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When this success payment was applied to subscription/invoice (idempotency).',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'M-Pesa payment'
        verbose_name_plural = 'M-Pesa payments'

    def __str__(self):
        return f'{self.payment_id} {self.phone} KES {self.amount} ({self.status})'

    @property
    def is_terminal(self):
        return self.status in (
            self.STATUS_SUCCESS,
            self.STATUS_FAILED,
            self.STATUS_CANCELLED,
        )


class Expenditure(models.Model):
    """Company spending record (opex / capex style entries)."""

    vendor = models.ForeignKey(
        'core.Vendor',
        on_delete=models.CASCADE,
        related_name='expenditures',
        null=True, blank=True,
    )

    METHOD_MPESA = 'mpesa'
    METHOD_BANK = 'bank'
    METHOD_CASH = 'cash'
    METHOD_CARD = 'card'
    METHOD_CHEQUE = 'cheque'
    METHOD_OTHER = 'other'
    METHOD_CHOICES = (
        (METHOD_MPESA, 'M-Pesa'),
        (METHOD_BANK, 'Bank transfer'),
        (METHOD_CASH, 'Cash'),
        (METHOD_CARD, 'Card'),
        (METHOD_CHEQUE, 'Cheque'),
        (METHOD_OTHER, 'Other'),
    )

    title = models.CharField(max_length=160)
    description = models.TextField(blank=True, default='')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=METHOD_CHOICES, default=METHOD_MPESA)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-occurred_at', '-id']
        verbose_name = 'Expenditure'
        verbose_name_plural = 'Expenditures'

    def __str__(self):
        return f'{self.title} — KES {self.amount}'


class Plan(models.Model):
    """ISP package / speed tier (monthly)."""

    vendor = models.ForeignKey(
        'core.Vendor',
        on_delete=models.CASCADE,
        related_name='plans',
        null=True, blank=True,
    )
    name = models.CharField(max_length=120)
    speed_mbps = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=12, decimal_places=2)
    mikrotik_profile = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text='RouterOS PPP/Hotspot profile name (Phase 4)',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['speed_mbps', 'price']
        verbose_name = 'Plan'
        verbose_name_plural = 'Plans'
        constraints = [
            models.UniqueConstraint(
                fields=['vendor', 'name'],
                name='billing_unique_vendor_plan_name',
            ),
        ]

    def __str__(self):
        return f'{self.name} — {self.speed_mbps} Mbps — KES {self.price}'


class Subscription(models.Model):
    """One customer ↔ plan link. At most one active per customer."""

    STATUS_ACTIVE = 'active'
    STATUS_PAUSED = 'paused'
    STATUS_EXPIRED = 'expired'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = (
        (STATUS_ACTIVE, 'Active'),
        (STATUS_PAUSED, 'Paused'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_CANCELLED, 'Cancelled'),
    )

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='subscriptions',
        limit_choices_to={'role': 'Customer'},
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='subscriptions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)
    started_at = models.DateTimeField(
        help_text='Service start (payment time). Expiry is exactly +1 calendar month at this clock time.',
    )
    expires_at = models.DateTimeField(
        db_index=True,
        help_text='Disconnect / renew deadline — same hour:minute:second as started_at, next month.',
    )
    expiry_reminder_for = models.DateTimeField(
        null=True,
        blank=True,
        help_text='expires_at value for which the 3-day SMS reminder was already sent.',
    )
    disconnect_task_id = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Celery task id for on-the-dot MikroTik disconnect at expires_at.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-started_at']
        verbose_name = 'Subscription'
        verbose_name_plural = 'Subscriptions'
        constraints = [
            models.UniqueConstraint(
                fields=['customer'],
                condition=Q(status='active'),
                name='billing_one_active_subscription_per_customer',
            ),
        ]

    def __str__(self):
        return f'{self.customer_id} → {self.plan} ({self.status})'


class Invoice(models.Model):
    """Bill for one subscription period."""

    STATUS_DRAFT = 'draft'
    STATUS_ISSUED = 'issued'
    STATUS_PARTIAL = 'partial'
    STATUS_PAID = 'paid'
    STATUS_OVERDUE = 'overdue'
    STATUS_VOID = 'void'
    STATUS_CHOICES = (
        (STATUS_DRAFT, 'Draft'),
        (STATUS_ISSUED, 'Issued'),
        (STATUS_PARTIAL, 'Partial'),
        (STATUS_PAID, 'Paid'),
        (STATUS_OVERDUE, 'Overdue'),
        (STATUS_VOID, 'Void'),
    )

    invoice_id = models.CharField(max_length=20, unique=True, default=_new_invoice_id, editable=False)
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name='invoices')
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    amount_due = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ISSUED, db_index=True)
    due_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-due_at', '-id']
        verbose_name = 'Invoice'
        verbose_name_plural = 'Invoices'

    def __str__(self):
        return f'{self.invoice_id} {self.status} KES {self.amount_due}'

    @property
    def balance(self):
        return self.amount_due - self.amount_paid


class NetworkServiceAccount(models.Model):
    """PPPoE secret on MikroTik linked to a customer (Phase 4)."""

    customer = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='network_account',
        limit_choices_to={'role': 'Customer'},
    )
    router = models.ForeignKey(
        'core.NetworkRouter',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='service_accounts',
    )
    username = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text='PPP secret name — usually 254XXXXXXXXX',
    )
    password = models.CharField(max_length=128, blank=True, default='')
    profile = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text='RouterOS PPP profile (e.g. 10Mbps)',
    )
    mikrotik_id = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text='RouterOS .id for the PPP secret',
    )
    disabled = models.BooleanField(default=False, db_index=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['username']
        verbose_name = 'Network service account'
        verbose_name_plural = 'Network service accounts'

    def __str__(self):
        state = 'disabled' if self.disabled else 'enabled'
        return f'{self.username} ({state})'
