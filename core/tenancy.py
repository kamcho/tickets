"""Multi-ISP (multi-vendor) request scope helpers."""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model

User = get_user_model()


def get_default_vendor():
    from core.models import Vendor

    slug = getattr(settings, 'DEFAULT_VENDOR_SLUG', 'metrolinks')
    return Vendor.objects.filter(slug=slug, is_active=True).first()


def resolve_vendor(request):
    """Active ISP tenant for this request."""
    if request is None:
        return get_default_vendor()

    host = (request.get_host() or '').split(':')[0].lower()
    labels = host.split('.')
    # tickets.acme.example.com → acme (optional future host routing)
    if len(labels) >= 3 and labels[0] in ('tickets', 'www'):
        from core.models import Vendor

        slug = labels[1] if labels[0] == 'tickets' and len(labels) >= 4 else labels[0]
        if slug not in ('www', 'tickets', 'localhost', '127'):
            vendor = Vendor.objects.filter(slug=slug, is_active=True).first()
            if vendor:
                return vendor

    user = getattr(request, 'user', None)
    if user and user.is_authenticated and getattr(user, 'vendor_id', None):
        return user.vendor

    return get_default_vendor()


def get_vendor(request):
    v = getattr(request, 'vendor', None)
    if v is not None:
        return v
    return resolve_vendor(request)


def is_platform_superadmin(user) -> bool:
    """Django superuser — sees and manages all vendors/tenants."""
    return bool(user and user.is_authenticated and user.is_superuser)


def is_vendor_admin(user) -> bool:
    """Tenant admin — manages one ISP (role Admin + vendor)."""
    return bool(
        user
        and user.is_authenticated
        and getattr(user, 'role', None) == 'Admin'
        and getattr(user, 'vendor_id', None)
        and not is_platform_superadmin(user),
    )


def _platform_sees_all(request) -> bool:
    return is_platform_superadmin(getattr(request, 'user', None))


def require_platform_superadmin(request):
    from django.core.exceptions import PermissionDenied

    if not is_platform_superadmin(getattr(request, 'user', None)):
        raise PermissionDenied('Platform super-admin access required.')


def scope_vendor(qs, request, *, field='vendor'):
    if _platform_sees_all(request):
        return qs
    vendor = get_vendor(request)
    if not vendor:
        return qs.none()
    return qs.filter(**{field: vendor})


def customers_qs(request):
    return scope_vendor(User.objects.filter(role='Customer'), request)


def staff_qs(request):
    return scope_vendor(User.objects.exclude(role='Customer'), request)


def tickets_qs(request):
    from core.models import Ticket

    return scope_vendor(Ticket.objects.all(), request)


def categories_qs(request):
    from core.models import TicketCategory

    return scope_vendor(TicketCategory.objects.all(), request)


def routers_qs(request):
    from core.models import NetworkRouter

    return scope_vendor(NetworkRouter.objects.all(), request)


def plans_qs(request):
    from billing.models import Plan

    return scope_vendor(Plan.objects.all(), request)


def expenditures_qs(request):
    from billing.models import Expenditure

    return scope_vendor(Expenditure.objects.all(), request)


def assign_vendor_on_save(instance, request):
    """Set vendor FK on new rows from the current request tenant."""
    if getattr(instance, 'vendor_id', None):
        return
    vendor = get_vendor(request)
    if vendor:
        instance.vendor = vendor


def vendor_branding(vendor):
    if not vendor:
        return {}
    return {
        'company_phone_primary': vendor.phone_primary or settings.COMPANY_PHONE_PRIMARY,
        'company_phone_secondary': vendor.phone_secondary or getattr(settings, 'COMPANY_PHONE_SECONDARY', ''),
        'company_email': vendor.email or getattr(settings, 'COMPANY_EMAIL', ''),
        'current_vendor': vendor,
        'current_vendor_name': vendor.name,
    }