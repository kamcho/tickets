"""Resolve customers by phone and pick the best match for tickets."""
import re

from django.contrib.auth import get_user_model
from django.db.models import Count, Q

from core.models import Ticket
from core.phone_utils import normalize_kenya_phone, phone_match_key

User = get_user_model()

_PHONE_IN_TEXT_RE = re.compile(
    r'(?:\+?254|0)?[17]\d{8}\b'
)


def extract_phone_from_text(text):
    """Find the first Kenyan mobile number in free text."""
    if not text:
        return ''
    for match in _PHONE_IN_TEXT_RE.finditer(str(text)):
        normalized = normalize_kenya_phone(match.group(0))
        if normalized:
            return normalized
    return ''


def customers_for_phone(phone):
    """All customer accounts that likely represent the same phone number."""
    key = phone_match_key(phone)
    if not key:
        return User.objects.none()

    filters = Q(phone__icontains=key)
    normalized = normalize_kenya_phone(phone)
    if normalized:
        filters |= Q(phone=normalized)
        local = '0' + normalized[3:]
        filters |= Q(phone=local)

    return (
        User.objects.filter(role='Customer')
        .filter(filters)
        .annotate(ticket_count=Count('customer_tickets'))
        .order_by('-ticket_count', 'id')
    )


def canonical_customer(phone=None, customer_id=None, customers=None):
    """
    Pick the customer record that should own this chat thread.

    Prefers accounts that already have tickets, then real email over wa_ placeholders.
    """
    if customer_id:
        found = User.objects.filter(pk=customer_id, role='Customer').first()
        if found:
            return found

    if customers is None:
        if not phone:
            return None
        customers = customers_for_phone(phone)

    rows = list(customers[:10])
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]

    def rank(user):
        real_email = 0 if (user.email or '').startswith('wa_') else 1
        tickets = getattr(user, 'ticket_count', None)
        if tickets is None:
            tickets = user.customer_tickets.count()
        return (tickets, real_email, -user.id)

    return max(rows, key=rank)


def link_conversation_customer(conversation, customer):
    if not conversation or not customer:
        return customer
    if conversation.customer_id != customer.id:
        conversation.customer = customer
        conversation.save(update_fields=['customer', 'updated_at'])
    return customer


def maybe_link_customer_from_message(conversation, text):
    phone = extract_phone_from_text(text)
    if not phone:
        return None
    customer = canonical_customer(phone=phone)
    if customer:
        link_conversation_customer(conversation, customer)
    return customer


def tickets_for_customers(customers, limit=15):
    if not customers:
        return Ticket.objects.none()
    if hasattr(customers, 'filter'):
        customer_ids = list(customers.values_list('pk', flat=True))
    else:
        customer_ids = [c.pk for c in customers]
    if not customer_ids:
        return Ticket.objects.none()
    return (
        Ticket.objects.filter(customer_id__in=customer_ids)
        .select_related('customer')
        .prefetch_related('categories')
        .order_by('-created_at')[:limit]
    )


def tickets_for_phone(phone, limit=15):
    customers = customers_for_phone(phone)
    return tickets_for_customers(customers, limit=limit), canonical_customer(customers=customers)


def tickets_for_conversation(conversation, limit=20):
    """Tickets for the linked customer, or all accounts matching their phone."""
    if not conversation:
        return [], None

    customer = conversation.customer if conversation.customer_id else None
    if customer:
        customers = customers_for_phone(customer.phone)
        if not customers.exists():
            customers = User.objects.filter(pk=customer.pk)
        canonical = canonical_customer(customers=customers) or customer
        link_conversation_customer(conversation, canonical)
        return list(tickets_for_customers(customers, limit=limit)), canonical

    if conversation.whatsapp_phone:
        tickets, canonical = tickets_for_phone(conversation.whatsapp_phone, limit=limit)
        if canonical:
            link_conversation_customer(conversation, canonical)
        return list(tickets), canonical

    return [], None
