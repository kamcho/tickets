"""Resolve MyUser from login identifier (phone preferred, email optional)."""
from django.contrib.auth import get_user_model

from core.phone_utils import normalize_kenya_phone, phone_match_key

User = get_user_model()


def looks_like_email(identifier):
    return '@' in (identifier or '')


def get_user_by_login_identifier(identifier):
    """
    Find user by phone (primary) or email.

    Phone accepts 07..., +254..., 254..., or 7XXXXXXXX.
    """
    identifier = (identifier or '').strip()
    if not identifier:
        return None

    if looks_like_email(identifier):
        return User.objects.filter(email__iexact=identifier).first()

    normalized = normalize_kenya_phone(identifier)
    if normalized:
        user = User.objects.filter(phone=normalized).first()
        if user:
            return user

    key = phone_match_key(identifier)
    if not key:
        return None

    for user in User.objects.filter(phone__icontains=key):
        if phone_match_key(user.phone) == key:
            return user
    return None
