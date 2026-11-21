"""High-level network ops: provision / suspend / restore + Celery disconnect schedule."""
import logging
import secrets
import string

from django.conf import settings
from django.utils import timezone

from billing.mikrotik import (
    MikroTikError,
    ensure_ppp_secret,
    get_default_router,
    kick_ppp,
    mikrotik_configured,
    set_ppp_disabled,
)
from core.phone_utils import normalize_kenya_phone

logger = logging.getLogger(__name__)


def _default_username(customer):
    if getattr(settings, 'MIKROTIK_USERNAME_IS_PHONE', True):
        phone = normalize_kenya_phone(customer.phone or '')
        if phone:
            return phone
    return f'cust{customer.pk}'


def _default_profile(subscription=None, plan=None):
    plan = plan or (subscription.plan if subscription else None)
    if plan and plan.mikrotik_profile:
        return plan.mikrotik_profile
    if plan:
        return f'{plan.speed_mbps}Mbps'
    return 'default'


def _random_password(length=12):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def resolve_router_for_account(*, router=None, account=None):
    """Pick NetworkRouter: explicit → account → DB default."""
    if router is not None:
        return router
    if account is not None and account.router_id:
        return account.router
    return get_default_router()


def get_or_create_account(customer, *, subscription=None, password=None, router=None):
    from billing.models import NetworkServiceAccount

    account = None
    try:
        account = customer.network_account
    except NetworkServiceAccount.DoesNotExist:
        account = None
    except AttributeError:
        account = NetworkServiceAccount.objects.filter(customer=customer).first()

    username = _default_username(customer)
    profile = _default_profile(subscription=subscription)
    target_router = router or resolve_router_for_account(account=account)

    if account is None:
        account = NetworkServiceAccount.objects.create(
            customer=customer,
            username=username,
            password=password or _random_password(),
            profile=profile,
            router=target_router,
        )
    else:
        changed = []
        if not account.username:
            account.username = username
            changed.append('username')
        if subscription and profile and account.profile != profile:
            account.profile = profile
            changed.append('profile')
        if password:
            account.password = password
            changed.append('password')
        if router is not None and account.router_id != router.pk:
            account.router = router
            changed.append('router')
        elif not account.router_id and target_router is not None:
            account.router = target_router
            changed.append('router')
        if changed:
            account.save(update_fields=changed + ['updated_at'])
    return account


def provision_account(customer, *, subscription=None, password=None, router=None):
    """Ensure local NetworkServiceAccount + PPP secret on the customer's router."""
    account = get_or_create_account(
        customer, subscription=subscription, password=password, router=router,
    )
    if not mikrotik_configured(account=account, router=account.router):
        account.last_error = 'mikrotik_not_configured'
        account.save(update_fields=['last_error', 'updated_at'])
        return account, {
            'ok': False,
            'error': 'mikrotik_not_configured',
            'skipped': True,
            'router': account.router.name if account.router_id else None,
        }

    try:
        row = ensure_ppp_secret(
            username=account.username,
            password=account.password,
            profile=account.profile or _default_profile(subscription=subscription),
            comment=f'customer:{customer.pk}',
            disabled=account.disabled,
            account=account,
            router=account.router,
        )
        account.mikrotik_id = str((row or {}).get('.id') or account.mikrotik_id or '')
        account.last_synced_at = timezone.now()
        account.last_error = ''
        account.save(update_fields=[
            'mikrotik_id', 'last_synced_at', 'last_error', 'updated_at',
        ])
        return account, {
            'ok': True,
            'username': account.username,
            'disabled': account.disabled,
            'router': account.router.name if account.router_id else 'env-default',
        }
    except MikroTikError as exc:
        account.last_error = str(exc)[:255]
        account.save(update_fields=['last_error', 'updated_at'])
        return account, {
            'ok': False,
            'error': 'mikrotik_unreachable' if exc.unreachable else str(exc),
            'unreachable': exc.unreachable,
            'router': account.router.name if account.router_id else None,
        }


def suspend_account(account, *, reason='expire'):
    """Disable PPP + kick on the account's router."""
    account.disabled = True
    account.save(update_fields=['disabled', 'updated_at'])

    if not mikrotik_configured(account=account):
        return {
            'ok': False,
            'username': account.username,
            'disabled': True,
            'kicked': False,
            'error': 'mikrotik_not_configured',
            'skipped': True,
            'reason': reason,
            'router': account.router.name if account.router_id else None,
        }

    kicked = 0
    try:
        set_ppp_disabled(account.username, disabled=True, account=account)
        kicked = kick_ppp(account.username, account=account)
        account.last_synced_at = timezone.now()
        account.last_error = ''
        account.save(update_fields=['last_synced_at', 'last_error', 'updated_at'])
        try:
            from billing.notifications import notify_service_suspended
            notify_service_suspended(account.customer, reason=reason)
        except Exception:
            logger.exception('Suspend SMS failed for %s', account.username)
        return {
            'ok': True,
            'username': account.username,
            'disabled': True,
            'kicked': kicked > 0,
            'reason': reason,
            'router': account.router.name if account.router_id else 'env-default',
        }
    except MikroTikError as exc:
        account.last_error = str(exc)[:255]
        account.save(update_fields=['last_error', 'updated_at'])
        return {
            'ok': False,
            'username': account.username,
            'disabled': True,
            'kicked': False,
            'error': 'mikrotik_unreachable' if exc.unreachable else str(exc),
            'unreachable': exc.unreachable,
            'router': account.router.name if account.router_id else None,
        }


def restore_account(account, *, subscription=None):
    """Enable PPP after payment on the account's router."""
    if subscription:
        profile = _default_profile(subscription=subscription)
        if profile and account.profile != profile:
            account.profile = profile

    account.disabled = False
    if subscription:
        account.save(update_fields=['disabled', 'profile', 'updated_at'])
    else:
        account.save(update_fields=['disabled', 'updated_at'])

    if not mikrotik_configured(account=account):
        return {
            'ok': False,
            'username': account.username,
            'disabled': False,
            'error': 'mikrotik_not_configured',
            'skipped': True,
            'router': account.router.name if account.router_id else None,
        }

    try:
        ensure_ppp_secret(
            username=account.username,
            password=account.password,
            profile=account.profile,
            comment=f'customer:{account.customer_id}',
            disabled=False,
            account=account,
            router=account.router,
        )
        account.last_synced_at = timezone.now()
        account.last_error = ''
        account.save(update_fields=['last_synced_at', 'last_error', 'mikrotik_id', 'updated_at'])
        try:
            from billing.notifications import notify_service_restored
            notify_service_restored(account.customer)
        except Exception:
            logger.exception('Restore SMS failed for %s', account.username)
        return {
            'ok': True,
            'username': account.username,
            'disabled': False,
            'router': account.router.name if account.router_id else 'env-default',
        }
    except MikroTikError as exc:
        account.last_error = str(exc)[:255]
        account.save(update_fields=['last_error', 'updated_at'])
        return {
            'ok': False,
            'username': account.username,
            'disabled': False,
            'error': 'mikrotik_unreachable' if exc.unreachable else str(exc),
            'unreachable': exc.unreachable,
            'router': account.router.name if account.router_id else None,
        }


def disconnect_task_id_for(subscription_id):
    return f'disconnect-sub-{subscription_id}'


def cancel_disconnect_task(subscription):
    task_id = subscription.disconnect_task_id or disconnect_task_id_for(subscription.pk)
    try:
        from ticket.celery import app as celery_app
        celery_app.control.revoke(task_id, terminate=False)
    except Exception:
        logger.info('Could not revoke disconnect task %s (broker down?)', task_id)
    if subscription.disconnect_task_id:
        subscription.disconnect_task_id = ''
        subscription.save(update_fields=['disconnect_task_id', 'updated_at'])


def schedule_disconnect(subscription):
    """
    Schedule on-the-dot MikroTik suspend at subscription.expires_at.
    Safe if Celery/Redis are down — logs and continues.
    """
    from billing.tasks import disconnect_subscription_at_expiry

    if not subscription or not subscription.expires_at:
        return None

    cancel_disconnect_task(subscription)
    task_id = disconnect_task_id_for(subscription.pk)
    eta = subscription.expires_at
    now = timezone.now()

    try:
        if eta <= now:
            async_result = disconnect_subscription_at_expiry.apply_async(
                args=[subscription.pk],
                task_id=task_id,
            )
        else:
            async_result = disconnect_subscription_at_expiry.apply_async(
                args=[subscription.pk],
                eta=eta,
                task_id=task_id,
            )
        subscription.disconnect_task_id = async_result.id or task_id
        subscription.save(update_fields=['disconnect_task_id', 'updated_at'])
        logger.info(
            'Scheduled disconnect sub=%s task=%s eta=%s',
            subscription.pk, subscription.disconnect_task_id, eta,
        )
        return subscription.disconnect_task_id
    except Exception:
        logger.exception('Failed to schedule disconnect for subscription %s', subscription.pk)
        return None


def on_subscription_activated(subscription):
    """After pay/start: provision+restore on router, schedule disconnect at expires_at."""
    customer = subscription.customer
    account, _ = provision_account(customer, subscription=subscription)
    restore_account(account, subscription=subscription)
    schedule_disconnect(subscription)
    return account


def on_subscription_expired(subscription, *, reason='expire'):
    """Cut access for an expired subscription."""
    customer = subscription.customer
    try:
        account = get_or_create_account(customer, subscription=subscription)
    except Exception:
        logger.exception('No network account for expired sub %s', subscription.pk)
        return None
    return suspend_account(account, reason=reason)
