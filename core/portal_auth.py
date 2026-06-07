"""Customer portal auth via Django session + MyUser (role=Customer)."""
from django.contrib.auth import login, logout
from django.shortcuts import redirect

from core.auth_utils import get_user_by_login_identifier
from core.phone_utils import digits_only, normalize_kenya_phone, phone_match_key

SESSION_CUSTOMER_KEY = 'portal_customer_id'  # legacy; cleared on login


def normalize_phone(phone):
    return digits_only(phone)


def get_portal_customer(request):
    """Logged-in customer user."""
    from core.customer_accounts import get_customer_user

    return get_customer_user(request.user)


def login_portal_user(request, user):
    login(request, user)
    request.session.pop(SESSION_CUSTOMER_KEY, None)


def logout_portal_customer(request):
    logout(request)
    request.session.pop(SESSION_CUSTOMER_KEY, None)


def customer_portal_required(view_func):
    """Require authenticated MyUser with role=Customer."""
    def wrapper(request, *args, **kwargs):
        from core.customer_accounts import get_customer_user

        if request.user.is_authenticated and get_customer_user(request.user):
            return view_func(request, *args, **kwargs)
        return redirect('portal_login')
    return wrapper


def customer_owns_ticket(customer_user, ticket):
    return ticket.customer_id == customer_user.id


def password_login_candidates(password):
    """
    Accept 07..., 254..., or +254... as the same phone-based password.
    """
    raw = (password or '').strip()
    if not raw:
        return []

    candidates = [raw]
    digits = digits_only(raw)
    if digits and digits not in candidates:
        candidates.append(digits)

    normalized = normalize_kenya_phone(raw)
    if normalized and normalized not in candidates:
        candidates.append(normalized)

    if normalized and normalized.startswith('254') and len(normalized) == 12:
        local = '0' + normalized[3:]
        if local not in candidates:
            candidates.append(local)

    return candidates


def check_portal_password(user, password):
    for candidate in password_login_candidates(password):
        if user.check_password(candidate):
            return True
    return False


def authenticate_customer(phone_or_email, password):
    """Portal sign-in: phone (primary) or email + password."""
    user = get_user_by_login_identifier(phone_or_email)
    if user is None:
        return None, 'not_found'
    if user.role != 'Customer':
        return None, 'staff_account'
    if not user.has_usable_password():
        return None, 'no_password'
    if not user.is_active:
        return None, 'inactive'
    if not check_portal_password(user, password):
        return None, 'bad_password'
    return user, 'ok'


def verify_ticket_access(ticket_id, phone):
    """Guest access: ticket ID + phone (logs in as customer user if linked)."""
    from core.models import Ticket

    key = phone_match_key(phone)
    if not ticket_id or not key:
        return None

    ticket = Ticket.objects.filter(
        ticket_id__iexact=ticket_id.strip(),
    ).select_related('customer').first()
    if not ticket or not ticket.customer_id:
        return None

    cust = ticket.customer
    if phone_match_key(cust.phone) == key:
        return ticket, cust
    return None
