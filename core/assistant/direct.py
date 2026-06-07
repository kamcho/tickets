"""Deterministic ticket/phone handling — do not rely on OpenAI to call tools."""
import re

from core.assistant.fallback import compose_fallback_reply
from core.assistant.tools import tool_get_customer_tickets, tool_lookup_ticket
from core.models import AssistantMessage
from core.phone_utils import digits_only, normalize_kenya_phone

TICKET_ID_RE = re.compile(r'\bTKT-[A-F0-9]{8}\b', re.I)

TICKET_INVENTORY_PHRASES = (
    'how many ticket',
    'my ticket',
    'any ticket',
    'do i have a ticket',
    'tickets do i have',
    'check my ticket',
    'open ticket',
    'list my ticket',
    'show my ticket',
    'ticket status',
    'have a ticket',
    'tickets are open',
    'tickets are pened',
    'tickets opened',
    'opened for me',
)


def extract_ticket_id(text):
    match = TICKET_ID_RE.search(text or '')
    return match.group(0).upper() if match else ''


def extract_phone(text):
    """Return normalized 254XXXXXXXXX if a Kenyan mobile is present."""
    raw = (text or '').strip()
    if not raw:
        return ''

    whole = normalize_kenya_phone(raw)
    if whole:
        return whole

    for chunk in re.findall(r'[\d+\s().-]{10,}', raw):
        normalized = normalize_kenya_phone(chunk)
        if normalized:
            return normalized

    compact = digits_only(raw)
    if len(compact) >= 9:
        normalized = normalize_kenya_phone(compact)
        if normalized:
            return normalized
    return ''


def is_ticket_inventory_question(text):
    lowered = (text or '').lower()
    return any(phrase in lowered for phrase in TICKET_INVENTORY_PHRASES)


def is_mostly_phone_message(text):
    phone = extract_phone(text)
    if not phone:
        return False
    remainder = digits_only(text)
    phone_digits = digits_only(phone)
    return remainder == phone_digits or remainder.endswith(phone_digits[-9:])


def assistant_recently_asked_for_phone(conversation):
    row = (
        conversation.messages.filter(role=AssistantMessage.ROLE_ASSISTANT)
        .order_by('-created_at')
        .first()
    )
    if not row:
        return False
    lowered = (row.content or '').lower()
    return any(
        phrase in lowered
        for phrase in (
            'phone number',
            'provide your phone',
            'your phone',
            'phone so i can',
            'share your phone',
        )
    )


def _first_ticket_id(result):
    tickets = result.get('tickets') or []
    return tickets[0].get('ticket_id') if tickets else None


def try_direct_reply(conversation, user_text, request=None):
    """
    Answer ticket-count / phone / ticket-id queries from the database directly.

    Returns (reply_text, highlight_ticket_id) or (None, None).
    """
    ticket_id = extract_ticket_id(user_text)
    if ticket_id:
        result = tool_lookup_ticket(
            ticket_id=ticket_id,
            conversation=conversation,
            request=request,
        )
        reply = compose_fallback_reply([('lookup_ticket', result)], request=request)
        if reply:
            return reply, ticket_id if not result.get('error') else None

    phone = extract_phone(user_text)
    asked_for_phone = assistant_recently_asked_for_phone(conversation)

    if not phone and conversation.customer_id and conversation.customer:
        if is_ticket_inventory_question(user_text):
            phone = normalize_kenya_phone(conversation.customer.phone) or conversation.customer.phone

    should_list_tickets = (
        phone
        and (
            is_mostly_phone_message(user_text)
            or asked_for_phone
            or is_ticket_inventory_question(user_text)
        )
    )

    if phone:
        result = tool_get_customer_tickets(
            phone=phone,
            conversation=conversation,
            request=request,
        )
        if not result.get('error'):
            reply = compose_fallback_reply([('get_customer_tickets', result)], request=request)
            if reply:
                return reply, _first_ticket_id(result)
        elif result.get('error') == 'Customer not found.':
            return (
                'I could not find a customer account for that phone number. '
                'Please double-check the number or contact Metrolinks support.',
                None,
            )

    if is_ticket_inventory_question(user_text) and conversation.customer_id:
        result = tool_get_customer_tickets(
            customer_id=conversation.customer_id,
            phone=phone or None,
            conversation=conversation,
            request=request,
        )
        reply = compose_fallback_reply([('get_customer_tickets', result)], request=request)
        if reply:
            return reply, _first_ticket_id(result)

    return None, None
