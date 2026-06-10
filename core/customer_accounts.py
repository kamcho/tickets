"""Customer accounts — MyUser with role=Customer only."""
from django.contrib.auth import get_user_model

from core.phone_utils import digits_only, normalize_kenya_phone, phone_match_key

User = get_user_model()


def normalize_phone(phone):
    """Digits only (legacy helper for comparisons)."""
    return digits_only(phone)


def default_customer_portal_password(phone):
    """Default portal password matches the customer's phone (e.g. 0712345678)."""
    normalized = normalize_kenya_phone(phone) or ''
    if normalized.startswith('254') and len(normalized) == 12:
        return '0' + normalized[3:]
    return digits_only(phone) or (phone or '').strip()


def split_contact_name(contact_name):
    parts = (contact_name or '').strip().split(None, 1)
    first = parts[0] if parts else 'Customer'
    last = parts[1] if len(parts) > 1 else ''
    return first, last


def get_customer_user(user):
    """Return user if they are a customer account."""
    if not user or not user.is_authenticated:
        return None
    if getattr(user, 'role', None) != 'Customer':
        return None
    return user


def _email_from_phone(phone):
    """Derive a stable internal email from phone when no email is provided."""
    digits = digits_only(normalize_kenya_phone(phone) or phone)
    return f'customer_{digits}@metrolinks.local'


def create_customer_user(contact_name, phone, password, email='', address='', location=''):
    """Create or update MyUser with role=Customer. Email is optional — derived from phone if omitted."""
    phone_normalized = normalize_kenya_phone(phone)
    if not phone_normalized:
        raise ValueError(
            f'Phone number {phone!r} is not a valid Kenyan mobile. '
            'Use 07…, 254…, or +254… format.'
        )
    if not email:
        email = _email_from_phone(phone_normalized)
    email = User.objects.normalize_email(email.strip())
    first_name, last_name = split_contact_name(contact_name)

    if User.objects.filter(email__iexact=email).exclude(role='Customer').exists():
        raise ValueError('This email is already used by a staff account.')

    # Also try to find by phone in case they registered without email
    existing_by_phone = None
    key = phone_match_key(phone_normalized)
    if key:
        for u in User.objects.filter(role='Customer'):
            if phone_match_key(u.phone) == key:
                existing_by_phone = u
                break

    user = User.objects.filter(email__iexact=email, role='Customer').first() or existing_by_phone
    if user:
        user.first_name = first_name
        user.last_name = last_name or user.last_name
        user.phone = phone_normalized or user.phone
        user.address = address or user.address
        user.location = location or user.location
        if password:
            user.set_password(password)
        user.save()
    else:
        if password:
            user = User.objects.create_user(
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name or '-',
                phone=phone_normalized,
                role='Customer',
                address=address or '',
                location=location or '',
                is_staff=False,
                is_active=True,
            )
        else:
            user = User(
                email=email,
                first_name=first_name,
                last_name=last_name or '-',
                phone=phone_normalized,
                role='Customer',
                address=address or '',
                location=location or '',
                is_staff=False,
                is_active=True,
            )
            user.set_unusable_password()
            user.save()
    return user


def find_customer_by_phone(phone):
    """Find an existing customer by phone number (any format)."""
    key = phone_match_key(phone)
    if not key:
        return None
    for user in User.objects.filter(role='Customer'):
        if phone_match_key(user.phone) == key:
            return user
    return None


def find_customer_by_email_phone(email, phone):
    """Legacy: find by email + phone. Falls back to phone-only if email not given."""
    email = (email or '').strip().lower()
    if not email:
        return find_customer_by_phone(phone)
    key = phone_match_key(phone)
    if not key:
        return None
    for user in User.objects.filter(email__iexact=email, role='Customer'):
        if phone_match_key(user.phone) == key:
            return user
    return None
