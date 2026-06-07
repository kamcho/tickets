"""Category suggestions and display helpers."""
import re

from core.models import TicketCategory


def suggest_category_ids(description, limit=6):
    """Return category PKs that best match the complaint description."""
    text = (description or '').strip().lower()
    if len(text) < 8:
        return []

    words = {w for w in re.findall(r'[a-z0-9]+', text) if len(w) > 2}
    scored = []

    for cat in TicketCategory.objects.all().only('id', 'name'):
        name_lower = cat.name.lower()
        cat_words = {w for w in re.findall(r'[a-z0-9]+', name_lower) if len(w) > 2}
        overlap = len(words & cat_words)
        if name_lower in text:
            overlap += 3
        for word in words:
            if word in name_lower or name_lower in word:
                overlap += 1
        if overlap > 0:
            scored.append((overlap, cat.id))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [pk for _, pk in scored[:limit]]


COMPLAINT_KEYWORDS = (
    'problem', 'issue', 'complain', 'complaint', 'broken', 'fault', 'error',
    'not working', "doesn't work", 'help with', 'support', 'trouble', 'failed',
    'outage', 'slow', 'down', 'fix', 'repair', 'wrong', 'missing', 'unable',
    'wifi', 'wi-fi', 'internet', 'connected', 'no internet', 'network',
)


def conversation_needs_category_picker(conversation, user_text):
    """
    Show the in-chat category picker only once at the start of a complaint.

    If the user already sent messages (e.g. more details after the bot asked),
    skip the picker and let the AI use stored or suggested categories.
    """
    if conversation.selected_category_ids:
        return False
    if not looks_like_complaint(user_text):
        return False
    prior_user_msgs = conversation.messages.filter(
        role='user',
    ).count()
    return prior_user_msgs == 0


def looks_like_complaint(text):
    """True when the user is likely describing a problem / opening a ticket."""
    t = (text or '').strip().lower()
    if len(t) < 12:
        return False
    if any(kw in t for kw in COMPLAINT_KEYWORDS):
        return True
    return len(t.split()) >= 10


def categories_payload(description=''):
    """All categories with suggested flag for UI pickers."""
    suggested = set(suggest_category_ids(description))
    return [
        {
            'id': c.id,
            'name': c.name,
            'suggested': c.id in suggested,
        }
        for c in TicketCategory.objects.order_by('name')
    ]


def resolve_categories(category_names=None, category_name='', category_ids=None):
    """Resolve one or more categories from names and/or ids."""
    seen = set()
    result = []

    id_list = category_ids or []
    if id_list:
        for cat in TicketCategory.objects.filter(pk__in=id_list):
            if cat.id not in seen:
                seen.add(cat.id)
                result.append(cat)

    names = list(category_names or [])
    if category_name:
        names.insert(0, category_name)
    for raw in names:
        name = (raw or '').strip()
        if not name:
            continue
        cat = TicketCategory.objects.filter(name__iexact=name).first()
        if cat and cat.id not in seen:
            seen.add(cat.id)
            result.append(cat)

    return result
