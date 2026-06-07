"""Terminal debug prints for SMS / assignment pipeline (visible in runserver console)."""
import sys

from django.conf import settings


def sms_debug_enabled():
    return getattr(settings, 'SMS_DEBUG_PRINT', settings.DEBUG)


def sms_debug(source, step, **details):
    """
    Print one pipeline step, e.g.:
      [TKT-SMS] source=ticket_create_page | step=assign_start | ticket_id='TKT-...'
    """
    if not sms_debug_enabled():
        return
    parts = [f'[TKT-SMS] source={source}', f'step={step}']
    for key, value in details.items():
        parts.append(f'{key}={value!r}')
    print(' | '.join(parts), file=sys.stderr, flush=True)


def sms_debug_ujumbe_config(source):
    """Log whether UjumbeSMS env/settings are present (never print API key)."""
    enabled = getattr(settings, 'UJUMBE_SMS_ENABLED', False)
    has_key = bool(getattr(settings, 'UJUMBE_SMS_API_KEY', ''))
    has_email = bool(getattr(settings, 'UJUMBE_SMS_EMAIL', ''))
    sms_debug(
        source,
        'ujumbe_config',
        UJUMBE_SMS_ENABLED=enabled,
        has_api_key=has_key,
        has_email=has_email,
        sender_id=getattr(settings, 'UJUMBE_SMS_SENDER_ID', ''),
        base_url=getattr(settings, 'UJUMBE_SMS_BASE_URL', ''),
        configured=enabled and has_key and has_email,
    )
