"""
Intent classification layer.

Runs before every AI inference step. Maps a raw user message (plus
conversation context) to one of a small number of well-known intents,
returning any entities extracted from the text.

This makes the system predictable: when the intent and entities are
obvious (user typed a phone number, a ticket ID, or a plain listing
question) we handle it deterministically without calling OpenAI.
"""
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from core.phone_utils import normalize_kenya_phone, digits_only


# ── Compiled patterns ───────────────────────────────────────────────────────

TICKET_ID_RE = re.compile(r'\bTKT-[A-F0-9]{8}\b', re.IGNORECASE)

# Liberal match: 07xx, 01xx, +2547xx, 2547xx with optional spaces/dashes.
# normalize_kenya_phone does the real validation.
_PHONE_TOKEN_RE = re.compile(
    r'(?:(?:\+?254|0)[17]\d[\d\s\-]{6,10}\d)',
)

_ONLY_PHONE_CHARS_RE = re.compile(r'[^\d\s\+\-\(\)]')


# ── Keyword lists ────────────────────────────────────────────────────────────

_TICKET_COUNT_KW = (
    'how many ticket',
    'number of ticket',
    'tickets do i have',
    'tickets have i',
    'count.*ticket',
    'ticket.*count',
)

_LOOKUP_TICKETS_KW = (
    'my ticket',
    'my tickets',
    'show ticket',
    'list ticket',
    'view ticket',
    'see ticket',
    'check ticket',
    'ticket status',
    'any ticket',
    'any open',
    'open ticket',
    'tickets opened',
    'tickets open',
    'opened for me',
    'tickets are open',
    'tickets pened',      # common typo
    'have a ticket',
    'do i have',
)

_CREATE_TICKET_KW = (
    'open a ticket',
    'create a ticket',
    'create ticket',
    'new ticket',
    'raise a ticket',
    'submit a ticket',
    'log a ticket',
    'file a ticket',
    'report an issue',
    'report a problem',
    'report issue',
    'make a ticket',
)

_GREET_TOKENS = frozenset(
    {'hi', 'hello', 'hey', 'hej', 'howdy', 'hola', 'sup', 'yo', 'good morning',
     'good afternoon', 'good evening', 'good day'}
)

# Phrases in the most-recent assistant message that signal "I just asked for a phone"
_ASKED_FOR_PHONE_PHRASES = (
    'phone number',
    'provide your phone',
    'your phone',
    'contact number',
    'mobile number',
    'share your number',
    'phone so i can',
    'send me your number',
    'what is your number',
)


# ── Intent types ─────────────────────────────────────────────────────────────

class IntentType(str, Enum):
    PROVIDE_PHONE  = 'provide_phone'   # user is giving their phone number
    LOOKUP_TICKETS = 'lookup_tickets'  # "show my tickets", "any open tickets?"
    TICKET_COUNT   = 'ticket_count'    # "how many tickets do I have"
    LOOKUP_TICKET  = 'lookup_ticket'   # specific TKT-XXXXXXXX
    CREATE_TICKET  = 'create_ticket'   # user wants to raise a new ticket
    GREET          = 'greet'           # hello / hi
    GENERAL        = 'general'         # everything else → full OpenAI inference


@dataclass
class Intent:
    type: IntentType
    phone: Optional[str] = None      # normalised 254XXXXXXXXX, or None
    ticket_id: Optional[str] = None  # upper-case TKT-XXXXXXXX, or None


# ── Entity helpers ────────────────────────────────────────────────────────────

def extract_ticket_id(text: str) -> Optional[str]:
    m = TICKET_ID_RE.search(text or '')
    return m.group(0).upper() if m else None


def extract_phone(text: str) -> Optional[str]:
    """
    Return the first valid Kenyan mobile found in *text*, normalised to
    254XXXXXXXXX format, or None.
    """
    raw = (text or '').strip()
    if not raw:
        return None

    # Try the whole string (user just typed their number)
    whole = normalize_kenya_phone(raw)
    if whole:
        return whole

    # Try each phone-like token
    for chunk in _PHONE_TOKEN_RE.findall(raw):
        norm = normalize_kenya_phone(re.sub(r'[\s\-]', '', chunk))
        if norm:
            return norm

    # Last resort: strip non-digit characters and try
    compact = digits_only(raw)
    if len(compact) >= 9:
        norm = normalize_kenya_phone(compact)
        if norm:
            return norm

    return None


def is_mostly_phone(text: str, phone: str) -> bool:
    """True when the message is essentially just a phone number."""
    phone_digits = digits_only(phone)
    msg_digits   = digits_only(text)
    non_phone_chars = len(_ONLY_PHONE_CHARS_RE.sub('', text.strip()))
    return (
        msg_digits == phone_digits
        or msg_digits.endswith(phone_digits[-9:])
        or non_phone_chars <= 4          # e.g. "My number: 0712345678"
    )


# ── Conversation context helpers ─────────────────────────────────────────────

def assistant_last_asked_for_phone(conversation) -> bool:
    """
    Return True when the most recent assistant message solicited a phone number.
    Safe to call with conversation=None.
    """
    if conversation is None:
        return False
    try:
        from core.models import AssistantMessage
        content = (
            conversation.messages
            .filter(role=AssistantMessage.ROLE_ASSISTANT)
            .order_by('-created_at')
            .values_list('content', flat=True)
            .first()
        ) or ''
        low = content.lower()
        return any(phrase in low for phrase in _ASKED_FOR_PHONE_PHRASES)
    except Exception:
        return False


# ── Classifier ────────────────────────────────────────────────────────────────

def classify(user_text: str, conversation=None) -> Intent:
    """
    Classify *user_text* into an Intent.

    ``conversation`` is used only for context signals, never mutated.
    """
    text = (user_text or '').strip()
    low  = text.lower()

    # ── entity extraction ────────────────────────────────────────────────────
    ticket_id = extract_ticket_id(text)
    phone     = extract_phone(text)

    # ── greeting (short message that starts with a greeting word) ────────────
    words = re.findall(r'\b\w+\b', low)
    if words and len(words) <= 4:
        head = ' '.join(words[:2])
        if head in _GREET_TOKENS or words[0] in _GREET_TOKENS:
            return Intent(IntentType.GREET)

    # ── explicit ticket ID ───────────────────────────────────────────────────
    if ticket_id:
        return Intent(IntentType.LOOKUP_TICKET, ticket_id=ticket_id)

    # ── user is responding with their phone number ───────────────────────────
    asked_for_phone = assistant_last_asked_for_phone(conversation)
    if phone and (is_mostly_phone(text, phone) or asked_for_phone):
        return Intent(IntentType.PROVIDE_PHONE, phone=phone)

    # ── ticket count ─────────────────────────────────────────────────────────
    if any(re.search(kw, low) for kw in _TICKET_COUNT_KW):
        return Intent(IntentType.TICKET_COUNT, phone=phone)

    # ── ticket listing ───────────────────────────────────────────────────────
    if any(kw in low for kw in _LOOKUP_TICKETS_KW):
        return Intent(IntentType.LOOKUP_TICKETS, phone=phone)

    # ── create ticket ─────────────────────────────────────────────────────────
    if any(kw in low for kw in _CREATE_TICKET_KW):
        return Intent(IntentType.CREATE_TICKET)

    # ── default: let OpenAI decide ────────────────────────────────────────────
    return Intent(IntentType.GENERAL)
