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





def send_sms(numbers, message, sender=None, source='unknown', context=''):

    """

    Send SMS via UjumbeSMS API.



    numbers: str, list, or comma-separated — normalized to 254XXXXXXXXX.

    Returns API JSON response dict or None if disabled/failed.

    """

    sms_debug(

        source,

        'ujumbe_send_start',

        context=context,

        raw_numbers=numbers,

        message_len=len(message or ''),

    )

    if not ujumbe_configured():

        sms_debug(source, 'ujumbe_send_skip', context=context, reason='not_configured')

        logger.debug('UjumbeSMS not configured; skipping send.')

        return None



    normalized = _normalize_recipients(numbers)

    if not normalized or not (message or '').strip():

        sms_debug(

            source,

            'ujumbe_send_skip',

            context=context,

            reason='invalid_numbers_or_empty_message',

            normalized_numbers=normalized,

        )

        logger.warning('UjumbeSMS: missing valid numbers or message (raw=%r).', numbers)

        return None



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

            sms_debug(

                source,

                'ujumbe_http_response',

                context=context,

                status_code=response.status_code,

                body_preview=(response.text or '')[:300],

            )

            response.raise_for_status()

            data = response.json()

            sms_debug(

                source,

                'ujumbe_send_ok',

                context=context,

                api_status=data.get('status'),

            )

            logger.info(

                'UjumbeSMS sent to %s — status %s',

                normalized,

                data.get('status', {}).get('description', 'ok'),

            )

            return data

    except httpx.HTTPError as exc:

        sms_debug(

            source,

            'ujumbe_send_fail',

            context=context,

            reason='http_error',

            error=str(exc),

        )

        logger.exception('UjumbeSMS HTTP error')

        return None

    except Exception as exc:

        sms_debug(

            source,

            'ujumbe_send_fail',

            context=context,

            reason='exception',

            error=str(exc),

        )

        logger.exception('UjumbeSMS send failed')

        return None

