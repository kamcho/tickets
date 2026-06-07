"""WhatsApp Cloud API (Meta) — send messages and parse webhooks."""
import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


def whatsapp_configured():
    return bool(
        getattr(settings, 'WHATSAPP_ACCESS_TOKEN', '')
        and getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', '')
    )


def send_whatsapp_text(to_phone, text):
    """Send a text message to a WhatsApp user (E.164 without + is fine)."""
    if not whatsapp_configured():
        logger.warning('WhatsApp not configured; message not sent.')
        return False

    token = settings.WHATSAPP_ACCESS_TOKEN
    phone_id = settings.WHATSAPP_PHONE_NUMBER_ID
    api_version = getattr(settings, 'WHATSAPP_API_VERSION', 'v21.0')
    to_digits = ''.join(c for c in str(to_phone) if c.isdigit())

    url = f'https://graph.facebook.com/{api_version}/{phone_id}/messages'
    payload = {
        'messaging_product': 'whatsapp',
        'to': to_digits,
        'type': 'text',
        'text': {'body': (text or '')[:4096]},
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                url,
                headers={'Authorization': f'Bearer {token}'},
                json=payload,
            )
            response.raise_for_status()
            return True
    except httpx.HTTPError:
        logger.exception('WhatsApp send failed to %s', to_digits)
        return False


def extract_inbound_messages(payload):
    """
    Yield dicts: {from_phone, text, profile_name, message_id} from Meta webhook JSON.
    """
    if not payload:
        return
    for entry in payload.get('entry', []):
        for change in entry.get('changes', []):
            value = change.get('value', {})
            contacts = {c.get('wa_id'): c.get('profile', {}).get('name', '') for c in value.get('contacts', [])}
            for message in value.get('messages', []):
                if message.get('type') != 'text':
                    continue
                wa_id = message.get('from', '')
                yield {
                    'from_phone': wa_id,
                    'text': message.get('text', {}).get('body', ''),
                    'profile_name': contacts.get(wa_id, ''),
                    'message_id': message.get('id', ''),
                }


def verify_webhook_token(mode, token, challenge):
    """Meta subscription verification."""
    verify = getattr(settings, 'WHATSAPP_VERIFY_TOKEN', '')
    if mode == 'subscribe' and token == verify:
        return challenge
    return None
