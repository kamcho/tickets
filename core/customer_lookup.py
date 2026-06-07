"""Resolve customers and tickets by phone — handles duplicate records / format mismatches."""
from django.contrib.auth import get_user_model
from django.db.models import Count

from core.models import Ticket
from core.phone_utils import phone_match_key

User = get_user_model()


def phone_keys_for(*phones):
    """Collect distinct 9-digit match keys from one or more phone strings."""
    keys = set()
    for raw in phones:
        if not raw:
            continue
        key = phone_match_key(raw)
        if key and len(key) >= 9:
            keys.add(key)
    return keys


def _customers_by_phone_keys(keys):
    """
    Match customers by normalized phone key (not SQL icontains).

    icontains misses numbers stored with spaces (e.g. ``254 728 507 155``) and can
    return the wrong row when multiple formats exist — we must compare via phone_match_key.
    """
    if not keys:
        return User.objects.none()
    matched_ids = []
    for user in User.objects.filter(role='Customer').only('id', 'phone'):
        user_key = phone_match_key(user.phone)
        if user_key and user_key in keys:
            matched_ids.append(user.id)
    if not matched_ids:
        return User.objects.none()
    return (
        User.objects.filter(pk__in=matched_ids, role='Customer')
        .annotate(ticket_count=Count('customer_tickets'))
        .order_by('-ticket_count', 'id')
    )


def customers_for_contact(*, phone=None, customer_id=None, conversation=None):
    """
    Find every customer record that shares the same contact number.

    Staff and the assistant may have created separate MyUser rows for the same
    person when phone was stored as 07XXXXXXXX vs 254XXXXXXXXX.
    """
    keys = phone_keys_for(phone)

    if customer_id:
        row = User.objects.filter(pk=customer_id, role='Customer').only('id', 'phone').first()
        if row:
            keys |= phone_keys_for(row.phone)

    if conversation is not None:
        if conversation.customer_id:
            if conversation.customer:
                keys |= phone_keys_for(conversation.customer.phone)
            else:
                row = User.objects.filter(pk=conversation.customer_id, role='Customer').only('phone').first()
                if row:
                    keys |= phone_keys_for(row.phone)
        if getattr(conversation, 'whatsapp_phone', None):
            keys |= phone_keys_for(conversation.whatsapp_phone)

    return _customers_by_phone_keys(keys)


def primary_customer(customers, conversation=None):
    """Prefer whoever has the most tickets (customers queryset is already ordered)."""
    return customers.first()


def _tickets_for_customer_ids(customer_ids, limit=15):
    if not customer_ids:
        return Ticket.objects.none()
    return (
        Ticket.objects.filter(customer_id__in=customer_ids)
        .prefetch_related('categories')
        .order_by('-created_at')[:limit]
    )


def _tickets_by_phone_keys(keys, limit=15):
    """Scan tickets when customer rows are ambiguous or missing."""
    if not keys:
        return Ticket.objects.none()
    matched_pks = []
    qs = (
        Ticket.objects.select_related('customer')
        .filter(customer__role='Customer')
        .order_by('-created_at')
    )
    for ticket in qs.iterator(chunk_size=100):
        if not ticket.customer_id:
            continue
        if phone_match_key(ticket.customer.phone) in keys:
            matched_pks.append(ticket.pk)
            if len(matched_pks) >= limit:
                break
    if not matched_pks:
        return Ticket.objects.none()
    return (
        Ticket.objects.filter(pk__in=matched_pks)
        .prefetch_related('categories')
        .order_by('-created_at')
    )


def tickets_for_contact(*, phone=None, customer_id=None, conversation=None, limit=15):
    customers = customers_for_contact(
        phone=phone, customer_id=customer_id, conversation=conversation,
    )
    keys = phone_keys_for(phone)
    if customer_id:
        row = User.objects.filter(pk=customer_id, role='Customer').only('phone').first()
        if row:
            keys |= phone_keys_for(row.phone)

    customer_ids = list(customers.values_list('pk', flat=True))
    tickets = _tickets_for_customer_ids(customer_ids, limit=limit)

    if not tickets.exists() and keys:
        tickets = _tickets_by_phone_keys(keys, limit=limit)
        if tickets.exists() and not customers.exists():
            owner_ids = {t.customer_id for t in tickets if t.customer_id}
            customers = _customers_by_phone_keys(keys).filter(pk__in=owner_ids)

    return customers, tickets


def link_conversation_to_best_customer(conversation, *, phone=None, customer_id=None):
    """Attach the chat thread to the customer record that owns tickets when possible."""
    if conversation is None:
        return None
    customers, tickets = tickets_for_contact(
        phone=phone, customer_id=customer_id, conversation=conversation, limit=1,
    )
    customer = None
    if tickets.exists() and tickets.first().customer_id:
        customer = tickets.first().customer
    if not customer:
        customer = customers.first()
    if customer and conversation.customer_id != customer.id:
        conversation.customer = customer
        conversation.save(update_fields=['customer', 'updated_at'])
    return customer


def customer_matches_phone(customer, phone):
    if not customer or not phone:
        return False
    user_key = phone_match_key(customer.phone)
    query_key = phone_match_key(phone)
    return bool(user_key and query_key and user_key == query_key)
