"""Resolve customers and tickets by phone — handles duplicate records / format mismatches."""
from django.contrib.auth import get_user_model
from django.db.models import Count, Q

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


def customers_queryset_for_phone_keys(keys):
    """All Customer-role users whose stored phone contains any of the match keys."""
    if not keys:
        return User.objects.none()
    phone_q = Q()
    for key in keys:
        phone_q |= Q(phone__icontains=key)
    qs = (
        User.objects.filter(role='Customer')
        .filter(phone_q)
        .annotate(ticket_count=Count('customer_tickets'))
        .order_by('-ticket_count', 'id')
    )
    if qs.exists():
        return qs
    # Fallback when phone is stored with spaces/formatting icontains cannot match.
    matched = []
    for user in User.objects.filter(role='Customer').annotate(
        ticket_count=Count('customer_tickets'),
    ):
        user_key = phone_match_key(user.phone)
        if user_key and user_key in keys:
            matched.append(user.pk)
    if not matched:
        return User.objects.none()
    return (
        User.objects.filter(pk__in=matched, role='Customer')
        .annotate(ticket_count=Count('customer_tickets'))
        .order_by('-ticket_count', 'id')
    )


def customers_for_contact(*, phone=None, customer_id=None, conversation=None):
    """
    Find every customer record that shares the same contact number.

    Staff and the assistant may have created separate MyUser rows for the same
    person when phone was stored as 07XXXXXXXX vs 254XXXXXXXXX (both are unique
    in the DB but share the same 9-digit suffix).
    """
    keys = phone_keys_for(phone)
    ids = set()

    if customer_id:
        row = User.objects.filter(pk=customer_id, role='Customer').first()
        if row:
            ids.add(row.id)
            keys |= phone_keys_for(row.phone)

    if conversation is not None:
        if conversation.customer_id:
            ids.add(conversation.customer_id)
            if conversation.customer:
                keys |= phone_keys_for(conversation.customer.phone)
        if getattr(conversation, 'whatsapp_phone', None):
            keys |= phone_keys_for(conversation.whatsapp_phone)

    qs = customers_queryset_for_phone_keys(keys)
    if qs.exists():
        return qs
    if ids:
        return (
            User.objects.filter(pk__in=ids, role='Customer')
            .annotate(ticket_count=Count('customer_tickets'))
            .order_by('-ticket_count', 'id')
        )
    return User.objects.none()


def primary_customer(customers, conversation=None):
    """Prefer the linked conversation customer, else whoever has the most tickets."""
    if conversation and conversation.customer_id:
        linked = customers.filter(pk=conversation.customer_id).first()
        if linked:
            return linked
    return customers.first()


def tickets_for_contact(*, phone=None, customer_id=None, conversation=None, limit=15):
    customers = customers_for_contact(
        phone=phone, customer_id=customer_id, conversation=conversation,
    )
    if not customers.exists():
        return customers, Ticket.objects.none()
    tickets = (
        Ticket.objects.filter(customer__in=customers)
        .prefetch_related('categories')
        .order_by('-created_at')[:limit]
    )
    return customers, tickets


def link_conversation_to_best_customer(conversation, *, phone=None, customer_id=None):
    """Attach the chat thread to the customer record that owns tickets when possible."""
    if conversation is None:
        return None
    customers = customers_for_contact(
        phone=phone, customer_id=customer_id, conversation=conversation,
    )
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
