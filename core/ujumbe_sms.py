"""UjumbeSMS client — https://ujumbesms.co.ke/api/messaging"""
import logging

import httpx
from django.conf import settings

from core.phone_utils import normalize_kenya_phone
from core.sms_debug import sms_debug

logger = logging.getLogger(__name__)

__all__ = ['ujumbe_configured', 'normalize_kenya_phone', 'send_sms']


def ujumbe_configured():
    return bool(
        getattr(settings, 'UJUMBE_SMS_ENABLED', False)
        and getattr(settings, 'UJUMBE_SMS_API_KEY', '')
        and getattr(settings, 'UJUMBE_SMS_EMAIL', '')
    )


def _normalize_recipients(numbers):
    if isinstance(numbers, (list, tuple)):
        parts = [normalize_kenya_phone(n) for n in numbers if n]
    elif ',' in str(numbers):
        parts = [
            normalize_kenya_phone(p.strip())
            for p in str(numbers).split(',')
        ]
    else:
        parts = [normalize_kenya_phone(numbers)]
    return ','.join(p for p in parts if p)


def _ujumbe_api_result(data):
    """
    Ujumbe returns HTTP 200 even when status.type is 'error' (e.g. code 1003 auth).

    Returns (ok: bool, message: str, status: dict|None).
    """
    if not isinstance(data, dict):
        return False, 'Invalid JSON response from UjumbeSMS.', None

    status = data.get('status')
    if not isinstance(status, dict):
        return True, '', None

    stype = (status.get('type') or '').strip().lower()
    if stype != 'error':
        desc = (status.get('description') or 'OK').strip()
        return True, desc, status

    code = str(status.get('code') or '').strip()
    desc = (status.get('description') or 'Unknown error').strip()
    msg = f'UjumbeSMS error {code}: {desc}' if code else f'UjumbeSMS error: {desc}'

    if code == '1003' or 'authentication' in desc.lower():
        msg += (
            ' Verify UJUMBE_SMS_EMAIL is the exact login email on ujumbesms.co.ke '
            'and UJUMBE_SMS_API_KEY is the current API key from the portal '
            '(regenerate if unsure).'
        )
    elif code == '1001' or 'balance' in desc.lower() or 'credit' in desc.lower():
        msg += ' Top up SMS credits on your Ujumbe account.'

    sender = getattr(settings, 'UJUMBE_SMS_SENDER_ID', '')
    if 'sender' in desc.lower() and sender and sender != 'UjumbeSMS':
        msg += f' Sender ID {sender!r} may need approval on Ujumbe.'

    return False, msg, status


def send_sms(numbers, message, sender=None, source='unknown', context=''):
    """
    Send SMS via UjumbeSMS API.

    Returns a dict:
      {'ok': True, 'numbers': '254…', 'data': {...}, 'http_status': 200}
      {'ok': False, 'error': '…', 'message': 'human-readable', ...}
    """
    sms_debug(
        source,
        'ujumbe_send_start',
        context=context,
        raw_numbers=numbers,
        message_len=len(message or ''),
    )

    if not ujumbe_configured():
        msg = (
            'UjumbeSMS is not configured. Set UJUMBE_SMS_ENABLED=True, '
            'UJUMBE_SMS_API_KEY, and UJUMBE_SMS_EMAIL.'
        )
        sms_debug(source, 'ujumbe_send_skip', context=context, reason='not_configured')
        logger.debug('UjumbeSMS not configured; skipping send.')
        return {'ok': False, 'error': 'not_configured', 'message': msg}

    normalized = _normalize_recipients(numbers)
    if not normalized or not (message or '').strip():
        msg = f'Invalid recipient or empty message (raw numbers={numbers!r}).'
        sms_debug(
            source,
            'ujumbe_send_skip',
            context=context,
            reason='invalid_numbers_or_empty_message',
            normalized_numbers=normalized,
        )
        logger.warning('UjumbeSMS: missing valid numbers or message (raw=%r).', numbers)
        return {'ok': False, 'error': 'invalid_payload', 'message': msg, 'numbers': normalized or ''}

    sender = (sender or getattr(settings, 'UJUMBE_SMS_SENDER_ID', 'UjumbeSMS')).strip()
    base_url = getattr(settings, 'UJUMBE_SMS_BASE_URL', 'https://ujumbesms.co.ke').rstrip('/')
    url = f'{base_url}/api/messaging'

    payload = {
        'data': [
            {
                'message_bag': {
                    'numbers': normalized,
                    'message': message.strip(),
                    'sender': sender,
                },
            },
        ],
    }

    headers = {
        'X-Authorization': settings.UJUMBE_SMS_API_KEY,
        'Email': settings.UJUMBE_SMS_EMAIL,
        'Content-Type': 'application/json',
        'Cache-Control': 'no-cache',
    }

    sms_debug(
        source,
        'ujumbe_http_post',
        context=context,
        url=url,
        numbers=normalized,
        sender=sender,
    )

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload, headers=headers)
            body_preview = (response.text or '')[:500]
            sms_debug(
                source,
                'ujumbe_http_response',
                context=context,
                status_code=response.status_code,
                body_preview=body_preview[:300],
            )
            response.raise_for_status()
            data = response.json()
            api_ok, api_msg, api_status = _ujumbe_api_result(data)

            if not api_ok:
                sms_debug(
                    source,
                    'ujumbe_send_fail',
                    context=context,
                    reason='api_status_error',
                    api_status=api_status,
                )
                logger.warning(
                    'UjumbeSMS API rejected send to %s: %s',
                    normalized,
                    api_msg,
                )
                return {
                    'ok': False,
                    'error': 'api_status_error',
                    'message': api_msg,
                    'numbers': normalized,
                    'data': data,
                    'http_status': response.status_code,
                    'body_preview': body_preview,
                    'api_status': api_status,
                }

            sms_debug(
                source,
                'ujumbe_send_ok',
                context=context,
                api_status=api_status,
            )
            logger.info(
                'UjumbeSMS sent to %s — %s',
                normalized,
                api_msg or 'ok',
            )
            return {
                'ok': True,
                'numbers': normalized,
                'data': data,
                'http_status': response.status_code,
                'body_preview': body_preview,
                'api_status': api_status,
            }
    except httpx.HTTPStatusError as exc:
        body = (exc.response.text or '')[:500]
        msg = f'HTTP {exc.response.status_code} from UjumbeSMS: {body or str(exc)}'
        sms_debug(
            source,
            'ujumbe_send_fail',
            context=context,
            reason='http_error',
            error=str(exc),
        )
        logger.exception('UjumbeSMS HTTP error')
        return {
            'ok': False,
            'error': 'http_error',
            'message': msg,
            'http_status': exc.response.status_code,
            'body': body,
            'numbers': normalized,
        }
    except httpx.HTTPError as exc:
        msg = f'Connection error calling UjumbeSMS: {exc}'
        sms_debug(
            source,
            'ujumbe_send_fail',
            context=context,
            reason='connection_error',
            error=str(exc),
        )
        logger.exception('UjumbeSMS connection error')
        return {
            'ok': False,
            'error': 'connection_error',
            'message': msg,
            'numbers': normalized,
        }
    except Exception as exc:
        msg = f'Unexpected error sending SMS: {exc}'
        sms_debug(
            source,
            'ujumbe_send_fail',
            context=context,
            reason='exception',
            error=str(exc),
        )
        logger.exception('UjumbeSMS send failed')
        return {
            'ok': False,
            'error': 'exception',
            'message': msg,
            'numbers': normalized,
        }
