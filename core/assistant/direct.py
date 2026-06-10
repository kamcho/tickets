"""
Deterministic intent-based reply layer.

Runs before every OpenAI call. When the user's intent and the data needed
to serve it are both clear, we query the database directly and return a
reply without spending an LLM inference round-trip.

Dispatch table
--------------
PROVIDE_PHONE   → fetch tickets for that phone number
LOOKUP_TICKETS  → fetch tickets for the linked customer (or ask for phone)
TICKET_COUNT    → same as LOOKUP_TICKETS
LOOKUP_TICKET   → fetch one specific ticket by ID
GREET / GENERAL → return (None, None) → caller will use OpenAI
CREATE_TICKET   → return (None, None) → caller forces tool_choice
"""
import logging

from core.assistant.fallback import compose_fallback_reply
from core.assistant.intent import (
    IntentType,
    classify,
    extract_phone,
    assistant_last_asked_for_phone,
)
from core.assistant.tools import tool_get_customer_tickets, tool_lookup_ticket
from core.phone_utils import normalize_kenya_phone

logger = logging.getLogger(__name__)

# Human-readable prompts reused in several branches
_ASK_FOR_PHONE = (
    'Please share your phone number so I can pull up your tickets.'
)
_INVALID_PHONE = (
    "I wasn't able to read that as a valid Kenyan mobile number. "
    'Please send it in the format 0712 345 678 or 254712345678.'
)
_NOT_FOUND = (
    'I could not find a customer account for that phone number. '
    'Please double-check the number or contact Metrolinks support directly.'
)


def _first_ticket_id(result: dict):
    tickets = result.get('tickets') or []
    return tickets[0].get('ticket_id') if tickets else None


def _phone_for_conversation(conversation) -> str:
    """Return the normalised phone of the customer linked to this conversation."""
    if not conversation or not conversation.customer_id:
        return ''
    customer = conversation.customer
    if not customer:
        return ''
    return normalize_kenya_phone(customer.phone) or customer.phone or ''


def _fetch_tickets(phone=None, customer_id=None, conversation=None, request=None):
    """
    Thin wrapper — always returns a dict, never raises.
    Returns (result_dict, reply_text | None).
    """
    try:
        result = tool_get_customer_tickets(
            phone=phone,
            customer_id=customer_id,
            conversation=conversation,
            request=request,
        )
    except Exception as exc:
        logger.exception('tool_get_customer_tickets raised: %s', exc)
        return {}, None

    if result.get('error') == 'Customer not found.':
        return result, _NOT_FOUND

    if result.get('error'):
        # Unexpected error — let OpenAI handle it
        return result, None

    reply = compose_fallback_reply([('get_customer_tickets', result)], request=request)
    return result, reply


def _fetch_ticket(ticket_id, conversation=None, request=None):
    """Thin wrapper for lookup_ticket, never raises."""
    try:
        result = tool_lookup_ticket(
            ticket_id=ticket_id,
            conversation=conversation,
            request=request,
        )
    except Exception as exc:
        logger.exception('tool_lookup_ticket raised: %s', exc)
        return {}, None

    if result.get('error'):
        return result, None

    reply = compose_fallback_reply([('lookup_ticket', result)], request=request)
    return result, reply


# ── Public entry point ────────────────────────────────────────────────────────

def try_direct_reply(conversation, user_text, request=None):
    """
    Attempt to answer *user_text* directly from the database.

    Returns
    -------
    (reply_text, active_ticket_id) — both str/None.

    If the intent cannot be resolved deterministically, returns (None, None)
    and the caller should proceed with OpenAI inference.
    """
    intent = classify(user_text, conversation=conversation)

    # ── Lookup one ticket by ID ───────────────────────────────────────────────
    if intent.type == IntentType.LOOKUP_TICKET:
        result, reply = _fetch_ticket(
            intent.ticket_id, conversation=conversation, request=request,
        )
        if reply:
            tid = None if result.get('error') else intent.ticket_id
            return reply, tid
        # Could not build a reply (unexpected error) — let OpenAI try
        return None, None

    # ── Intents that require a phone / customer ───────────────────────────────
    if intent.type in (
        IntentType.PROVIDE_PHONE,
        IntentType.LOOKUP_TICKETS,
        IntentType.TICKET_COUNT,
    ):
        phone = intent.phone

        # If the user's message didn't contain a phone, fall back to the
        # conversation's linked customer phone.
        if not phone:
            phone = _phone_for_conversation(conversation)

        # PROVIDE_PHONE with an unreadable number → tell the user immediately.
        if intent.type == IntentType.PROVIDE_PHONE and not phone:
            # They sent something that looked phone-like but couldn't be parsed.
            raw_phone = extract_phone(user_text)
            if not raw_phone:
                return _INVALID_PHONE, None

        # Still no phone and no linked customer → ask for the number.
        if not phone:
            return _ASK_FOR_PHONE, None

        result, reply = _fetch_tickets(
            phone=phone,
            customer_id=conversation.customer_id if conversation else None,
            conversation=conversation,
            request=request,
        )

        if reply:
            return reply, _first_ticket_id(result)

        # Unexpected error from the tool — fall through to OpenAI.
        return None, None

    # ── All other intents (GREET, CREATE_TICKET, GENERAL) ────────────────────
    # Let the caller (agent.py) decide — OpenAI inference or forced tool call.
    return None, None
