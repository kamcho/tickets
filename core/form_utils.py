"""Shared form helpers."""
from django import forms

from core.phone_utils import normalize_kenya_phone


def clean_kenya_mobile_phone(raw, *, required=True, field_label='Phone'):
    """
    Normalize to 254XXXXXXXXX for storage and SMS.

    Accepts 07..., +254..., 254..., or 7XXXXXXXX.
    """
    value = (raw or '').strip()
    if not value:
        if required:
            raise forms.ValidationError(f'{field_label} is required.')
        return ''

    normalized = normalize_kenya_phone(value)
    if normalized:
        return normalized

    raise forms.ValidationError(
        f'Enter a valid Kenyan mobile number for {field_label} '
        f'(e.g. 0712 345 678 or +254 712 345 678).'
    )
