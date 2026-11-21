"""Staff JSON API for MikroTik PPPoE accounts (Phase 4)."""
import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from billing.mikrotik import MikroTikError, health, list_ppp_active, mikrotik_configured
from billing.models import NetworkServiceAccount, Subscription
from billing.network_services import (
    get_or_create_account,
    provision_account,
    restore_account,
    schedule_disconnect,
    suspend_account,
)
from billing.views import _require_billing_staff

logger = logging.getLogger(__name__)


def _json_body(request):
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return {}


@login_required(login_url='/login/')
@require_GET
def network_health(request):
    _require_billing_staff(request.user)
    if request.user.role != 'Admin':
        return JsonResponse({'ok': False, 'error': 'admin_only'}, status=403)
    router_id = request.GET.get('router_id')
    router = None
    if router_id:
        from core.models import NetworkRouter
        router = get_object_or_404(NetworkRouter, pk=router_id)
    if not mikrotik_configured(router=router):
        return JsonResponse({
            'ok': False,
            'error': 'mikrotik_not_configured',
            'configured': False,
        })
    try:
        data = health(router=router)
        return JsonResponse({
            'ok': True,
            'configured': True,
            'router': router.name if router else 'default',
            'resource': data,
        })
    except MikroTikError as exc:
        return JsonResponse({
            'ok': False,
            'error': 'mikrotik_unreachable',
            'detail': str(exc),
        }, status=502)


@login_required(login_url='/login/')
@require_GET
def network_router_list(request):
    """List active routers for staff provisioning UI."""
    _require_billing_staff(request.user)
    from core.models import NetworkRouter
    rows = []
    for r in NetworkRouter.objects.filter(is_active=True).order_by('name'):
        rows.append({
            'id': r.pk,
            'name': r.name,
            'location': r.location,
            'is_default': r.is_default,
            'has_api': r.has_api_credentials(),
            'host': r.effective_api_host,
        })
    return JsonResponse({
        'ok': True,
        'routers': rows,
        'env_fallback': mikrotik_configured(),
    })


@login_required(login_url='/login/')
@require_http_methods(['POST'])
def network_account_create(request):
    """Provision PPPoE for a customer (body: customer_id, optional password, router_id)."""
    _require_billing_staff(request.user)
    body = _json_body(request)
    customer_id = body.get('customer_id')
    if not customer_id:
        return JsonResponse({'ok': False, 'error': 'customer_id_required'}, status=400)

    from django.contrib.auth import get_user_model
    from core.models import NetworkRouter

    User = get_user_model()
    customer = get_object_or_404(User, pk=customer_id, role='Customer')
    router = None
    if body.get('router_id'):
        router = get_object_or_404(NetworkRouter, pk=body['router_id'], is_active=True)
    sub = (
        Subscription.objects.filter(customer=customer, status=Subscription.STATUS_ACTIVE)
        .select_related('plan')
        .first()
    )
    account, result = provision_account(
        customer,
        subscription=sub,
        password=body.get('password') or None,
        router=router,
    )
    if sub:
        schedule_disconnect(sub)
    status = 200 if result.get('ok') or result.get('skipped') else 502
    return JsonResponse({
        'ok': result.get('ok', False),
        'id': account.pk,
        'username': account.username,
        'disabled': account.disabled,
        'profile': account.profile,
        'router_id': account.router_id,
        **{k: v for k, v in result.items() if k not in ('ok',)},
    }, status=status)


@login_required(login_url='/login/')
@require_POST
def network_account_suspend(request, pk):
    _require_billing_staff(request.user)
    account = get_object_or_404(NetworkServiceAccount, pk=pk)
    result = suspend_account(account, reason='staff')
    status = 200 if result.get('ok') or result.get('skipped') else 502
    return JsonResponse(result, status=status)


@login_required(login_url='/login/')
@require_POST
def network_account_restore(request, pk):
    _require_billing_staff(request.user)
    account = get_object_or_404(NetworkServiceAccount, pk=pk)
    sub = (
        Subscription.objects.filter(
            customer=account.customer, status=Subscription.STATUS_ACTIVE,
        ).select_related('plan').first()
    )
    result = restore_account(account, subscription=sub)
    if sub:
        schedule_disconnect(sub)
    status = 200 if result.get('ok') or result.get('skipped') else 502
    return JsonResponse(result, status=status)


@login_required(login_url='/login/')
@require_POST
def network_account_kick(request, pk):
    _require_billing_staff(request.user)
    account = get_object_or_404(NetworkServiceAccount, pk=pk)
    if not mikrotik_configured(account=account):
        return JsonResponse({
            'ok': False,
            'error': 'mikrotik_not_configured',
            'username': account.username,
        }, status=502)
    try:
        from billing.mikrotik import kick_ppp
        n = kick_ppp(account.username, account=account)
        return JsonResponse({'ok': True, 'username': account.username, 'kicked': n > 0, 'count': n})
    except MikroTikError as exc:
        return JsonResponse({
            'ok': False,
            'error': 'mikrotik_unreachable' if exc.unreachable else str(exc),
            'username': account.username,
        }, status=502)


@login_required(login_url='/login/')
@require_GET
def network_account_status(request, pk):
    _require_billing_staff(request.user)
    account = get_object_or_404(NetworkServiceAccount.objects.select_related('router'), pk=pk)
    online = False
    if mikrotik_configured(account=account):
        try:
            online = len(list_ppp_active(account.username, account=account)) > 0
        except MikroTikError:
            online = False
    return JsonResponse({
        'username': account.username,
        'disabled': account.disabled,
        'online': online,
        'profile': account.profile,
        'router': account.router.name if account.router_id else 'default',
        'router_id': account.router_id,
        'last_error': account.last_error,
        'mikrotik_configured': mikrotik_configured(account=account),
    })


@login_required(login_url='/login/')
@require_POST
def network_account_ensure_for_customer(request, customer_id):
    """Convenience: get/create account for customer and return status."""
    _require_billing_staff(request.user)
    from django.contrib.auth import get_user_model
    User = get_user_model()
    customer = get_object_or_404(User, pk=customer_id, role='Customer')
    sub = (
        Subscription.objects.filter(customer=customer, status=Subscription.STATUS_ACTIVE)
        .select_related('plan')
        .first()
    )
    account = get_or_create_account(customer, subscription=sub)
    return JsonResponse({
        'ok': True,
        'id': account.pk,
        'username': account.username,
        'disabled': account.disabled,
        'profile': account.profile,
    })
