"""Detect duplicate open tickets for the same complaint."""
import re

from core.models import Ticket

OPEN_STATUSES = ('Open', 'In Progress', 'On Hold')

_STOPWORDS = frozenset({
    'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'her', 'was',
    'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his', 'how', 'its', 'may',
    'new', 'now', 'old', 'see', 'two', 'way', 'who', 'boy', 'did', 'she', 'use',
    'her', 'that', 'this', 'with', 'have', 'from', 'they', 'been', 'were', 'said',
    'each', 'which', 'their', 'will', 'other', 'about', 'many', 'then', 'them',
    'these', 'some', 'would', 'make', 'like', 'into', 'time', 'very', 'when',
    'come', 'could', 'than', 'first', 'been', 'call', 'after', 'most', 'over',
    'such', 'please', 'help', 'need', 'just', 'also', 'still', 'being', 'here',
})


def _significant_words(text):
    return {
        w for w in re.findall(r'[a-z0-9]{3,}', (text or '').lower())
        if w not in _STOPWORDS
    }


def descriptions_match(description_a, description_b):
    """True when two complaint texts are likely the same issue."""
    wa = _significant_words(description_a)
    wb = _significant_words(description_b)
    if not wa or not wb:
        return False
    shared = wa & wb
    if len(shared) >= 3:
        return True
    ratio = len(shared) / min(len(wa), len(wb))
    return ratio >= 0.28


def find_matching_open_ticket(customer, categories, description):
    """
    Return an existing open ticket for this customer that matches the complaint
    (shared category + similar description), or None.
    """
    if not customer or not categories:
        return None

    category_ids = {c.id for c in categories}
    description = (description or '').strip()

    candidates = (
        Ticket.objects.filter(customer=customer, status__in=OPEN_STATUSES)
        .prefetch_related('categories')
        .order_by('-created_at')
    )

    for ticket in candidates:
        ticket_cat_ids = set(ticket.categories.values_list('id', flat=True))
        if not category_ids & ticket_cat_ids:
            continue
        if descriptions_match(description, ticket.description):
            return ticket

    return None


def duplicate_ticket_response(ticket):
    from core.ticket_urls import ticket_detail_url

    url = ticket_detail_url(ticket.ticket_id, for_customer=True)
    return {
        'success': False,
        'duplicate': True,
        'ticket_id': ticket.ticket_id,
        'detail_url': url,
        'status': ticket.status,
        'priority': ticket.priority,
        'categories': ticket.categories_display,
        'created_at': ticket.created_at.isoformat(),
        'message': (
            f'A support ticket for this issue is already open ({ticket.ticket_id}). '
            f'Our technicians are handling it — current status: {ticket.status}. '
            f'View your ticket: {url} '
            f'You do not need to log the same complaint again.'
        ),
    }
