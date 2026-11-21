"""Celery tasks for on-the-dot MikroTik disconnect / restore retries."""
import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def disconnect_subscription_at_expiry(self, subscription_id):
    """
    Fire at subscription.expires_at: mark expired + suspend PPPoE + kick.
    Retries if MikroTik is unreachable.
    """
    from billing.models import Subscription
    from billing.network_services import on_subscription_expired
    from billing.services import mark_expired_subscriptions

    try:
        sub = Subscription.objects.select_related('customer', 'plan').get(pk=subscription_id)
    except Subscription.DoesNotExist:
        logger.warning('disconnect: subscription %s gone', subscription_id)
        return {'ok': False, 'error': 'not_found'}

    now = timezone.now()
    if sub.expires_at and sub.expires_at > now:
        # Renewed / rescheduled — do nothing
        logger.info(
            'disconnect skipped sub=%s expires_at=%s still in future',
            subscription_id, sub.expires_at,
        )
        return {'ok': False, 'error': 'not_due', 'expires_at': str(sub.expires_at)}

    mark_expired_subscriptions(now=now)
    sub.refresh_from_db()

    result = on_subscription_expired(sub, reason='expire')
    if result and result.get('unreachable'):
        raise self.retry(exc=Exception(result.get('error') or 'mikrotik_unreachable'))

    sub.disconnect_task_id = ''
    sub.save(update_fields=['disconnect_task_id', 'updated_at'])
    return result or {'ok': True, 'subscription_id': subscription_id}


@shared_task(bind=True, max_retries=5, default_retry_delay=45)
def restore_subscription_network(self, subscription_id):
    """Restore PPPoE after payment; retry on router failure (never blocks STK callback)."""
    from billing.models import Subscription
    from billing.network_services import get_or_create_account, restore_account, schedule_disconnect

    try:
        sub = Subscription.objects.select_related('customer', 'plan').get(pk=subscription_id)
    except Subscription.DoesNotExist:
        return {'ok': False, 'error': 'not_found'}

    account = get_or_create_account(sub.customer, subscription=sub)
    result = restore_account(account, subscription=sub)
    schedule_disconnect(sub)

    if result.get('unreachable'):
        raise self.retry(exc=Exception(result.get('error') or 'mikrotik_unreachable'))
    return result
