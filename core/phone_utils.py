"""Kenya phone normalization for storage, matching, and UjumbeSMS."""
import re

# UjumbeSMS: comma-separated 254XXXXXXXXX (12 digits, no + sign).
_KENYA_MOBILE_RE = re.compile(r'^254[17]\d{8}$')


def digits_only(phone):
    """Strip to digits only (for fuzzy matching)."""
    return re.sub(r'\D', '', str(phone or '').strip())


def normalize_kenya_phone(phone):
    """
    Convert common Kenyan inputs to UjumbeSMS format: 254XXXXXXXXX.

    Examples:
      0712345678      -> 254712345678
      +254 712 345 678 -> 254712345678
      712345678       -> 254712345678
      254712345678    -> 254712345678

    Returns '' if the number cannot be normalized to a valid Kenyan mobile.
    """
    digits = digits_only(phone)
    if not digits:
        return ''

    if digits.startswith('00'):
        digits = digits[2:]

    # Mistaken double prefix: 2540712... or 25407...
    if digits.startswith('2540'):
        digits = '254' + digits[4:]

    if digits.startswith('254'):
        pass
    elif digits.startswith('0'):
        digits = '254' + digits[1:]
    elif len(digits) == 9:
        digits = '254' + digits
    else:
        return ''

    if not _KENYA_MOBILE_RE.match(digits):
        return ''

    return digits


def is_valid_kenya_mobile(phone):
    return bool(normalize_kenya_phone(phone))


def phone_match_key(phone):
    """Last 9 digits (national significant number) for lookups."""
    normalized = normalize_kenya_phone(phone)
    if normalized:
        return normalized[-9:]
    digits = digits_only(phone)
    return digits[-9:] if len(digits) >= 9 else digits
