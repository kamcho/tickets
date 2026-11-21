"""Billing SMS: payment received + expiry reminders (UjumbeSMS)."""

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.utils.formats import date_format

from core.notifications import _first_name, _sms_to_user
from core.ujumbe_sms import ujumbe_configured

logger = logging.getLogger(__name__)


def _support_line():
    phone = getattr(settings, 'COMPANY_PHONE_PRIMARY', '') or ''
    return f' Call {phone}.' if phone else ''


def _fmt_when(dt):
    if not dt:
        return ''
    local = timezone.localtime(dt)
    return date_format(local, "j M Y, g:i A")


def notify_payment_received(payment, subscription):
    """SMS customer after a successful payment renews/starts their subscription."""
    if not ujumbe_configured():
        return False
    customer = getattr(subscription, 'customer', None) or getattr(payment, 'customer', None)
    if not customer:
        return False

    name = _first_name(customer)
    amount = payment.amount
    receipt = (payment.mpesa_receipt_number or '').strip() or 'N/A'
    until = _fmt_when(subscription.expires_at)
    plan = getattr(subscription, 'plan', None)
    plan_bit = f' ({plan.speed_mbps} Mbps)' if plan else ''

    message = (
        f'Dear {name}, payment of KES {amount} received (Receipt {receipt}). '
        f'Your Metrolinks internet{plan_bit} is active until {until}.'
        f'{_support_line()}'
    )
    try:
        return _sms_to_user(
            customer,
            message,
            context_label=f'payment_received:{payment.payment_id}',
            source='billing_payment',
        )
    except Exception:
        logger.exception('Payment SMS failed for %s', payment.payment_id)
        return False


def notify_expiry_reminder(subscription):
    """SMS that service expires in ~3 days. Caller handles idempotency."""
    if not ujumbe_configured():
        return False
    customer = subscription.customer
    if not customer:
        return False

    name = _first_name(customer)
    until = _fmt_when(subscription.expires_at)
    plan = subscription.plan
    price = plan.price if plan else ''
    speed = f'{plan.speed_mbps} Mbps' if plan else 'plan'

    message = (
        f'Dear {name}, your Metrolinks {speed} package expires on {until}. '
        f'Renew with KES {price} via M-Pesa to stay connected.'
        f'{_support_line()}'
    )
    try:
        return _sms_to_user(
            customer,
            message,
            context_label=f'expiry_reminder:sub:{subscription.pk}',
            source='billing_expiry',
        )
    except Exception:
        logger.exception('Expiry SMS failed for subscription %s', subscription.pk)
        return False


def send_due_expiry_reminders(*, now=None, days=3):
    """
    Send one SMS per active subscription whose expires_at falls within `days`
    from now, and for which we have not already reminded for that expires_at.
    Returns count sent.
    """
    from billing.models import Subscription

    now = now or timezone.now()
    window_end = now + timedelta(days=days)
    sent = 0

    qs = (
        Subscription.objects.filter(
            status=Subscription.STATUS_ACTIVE,
            expires_at__gt=now,
            expires_at__lte=window_end,
        )
        .select_related('customer', 'plan')
        .order_by('expires_at')
    )

    for sub in qs:
        # Already reminded for this exact expiry (renewal resets expires_at → new reminder)
        if sub.expiry_reminder_for and sub.expiry_reminder_for == sub.expires_at:
            continue
        ok = notify_expiry_reminder(sub)
        if ok:
            sub.expiry_reminder_for = sub.expires_at
            sub.save(update_fields=['expiry_reminder_for', 'updated_at'])
            sent += 1
        elif not ujumbe_configured():
            break

    return sent


def notify_service_suspended(customer, *, reason='expire'):
    if not ujumbe_configured() or not customer:
        return False
    name = _first_name(customer)
    message = (
        f'Dear {name}, your Metrolinks internet has been suspended'
        f'{" (subscription expired)" if reason == "expire" else ""}. '
        f'Pay via M-Pesa to restore service.{_support_line()}'
    )
    try:
        return _sms_to_user(
            customer, message,
            context_label=f'service_suspended:{customer.pk}',
            source='billing_network',
        )
    except Exception:
        logger.exception('Suspend SMS failed for customer %s', customer.pk)
        return False


def notify_service_restored(customer):
    if not ujumbe_configured() or not customer:
        return False
    name = _first_name(customer)
    message = (
        f'Dear {name}, your Metrolinks internet has been restored. '
        f'Thank you for your payment.{_support_line()}'
    )
    try:
        return _sms_to_user(
            customer, message,
            context_label=f'service_restored:{customer.pk}',
            source='billing_network',
        )
    except Exception:
        logger.exception('Restore SMS failed for customer %s', customer.pk)
        return False
