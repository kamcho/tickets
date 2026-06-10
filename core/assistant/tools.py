"""
Tool schemas (for OpenAI) and executors (Django).

OpenAI reads TOOL_SCHEMAS and chooses calls; execute_tool() only runs what the model requested.
"""
import json
import re
from django.contrib.auth import get_user_model
from django.db.models import Q

from core.category_utils import resolve_categories, suggest_category_ids
from core.ticket_matching import duplicate_ticket_response, find_matching_open_ticket
from core.ticket_urls import ticket_detail_url
from core.customer_accounts import create_customer_user
from core.models import Ticket, TicketCategory
from core.customer_lookup import (
    customer_matches_phone,
    customers_for_contact,
    link_conversation_to_best_customer,
    primary_customer,
    tickets_for_contact,
)

from core.phone_utils import digits_only, normalize_kenya_phone, phone_match_key

User = get_user_model()


def _normalize_phone(phone):
    if not phone:
        return ''
    return normalize_kenya_phone(phone) or digits_only(phone)


def _customer_email_fallback(phone, email=''):
    email = (email or '').strip()
    if email:
        return email
    digits = _normalize_phone(phone)
    if not digits:
        return ''
    return f'wa_{digits}@customers.metrolinkssolutionltd.local'


def _resolve_customer(customer_id=None, phone=None, conversation=None):
    customers = customers_for_contact(
        phone=phone, customer_id=customer_id, conversation=conversation,
    )
    return primary_customer(customers, conversation)


def _customers_for_phone(phone):
    return customers_for_contact(phone=phone)


def _customer_payload(user):
    return {
        'id': user.id,
        'contact_name': user.display_name,
        'phone': user.phone,
        'email': user.email,
    }


def _categories_label(categories):
    return ', '.join(c.name for c in categories) if categories else ''


TOOL_SCHEMAS = [
    {
        'type': 'function',
        'function': {
            'name': 'get_user_context',
            'description': (
                'Fetch all data available for the current user: their profile, every ticket they '
                'have ever raised (with status, priority, categories, description), and all '
                'available ticket categories. Call this whenever you are unsure what the user is '
                'asking about, need full ticket history to answer a question, or want to give a '
                'personalised response without asking the user to repeat themselves.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'customer_id': {'type': 'integer', 'description': 'Customer id if known'},
                    'phone': {'type': 'string', 'description': 'Customer phone if id unknown'},
                },
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'search_customers',
            'description': (
                'Use when the user mentions a name/phone/email and you need to find their customer record '
                'before listing tickets or creating a ticket.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'query': {'type': 'string', 'description': 'Name, phone, or email fragment to search'},
                },
                'required': ['query'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'list_ticket_categories',
            'description': (
                'Use when the user asks what kinds of issues you support, or before create_support_ticket '
                'if you need valid category names.'
            ),
            'parameters': {'type': 'object', 'properties': {}},
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'get_customer_tickets',
            'description': (
                'Use when the user wants to see their tickets, check open issues, or asks '
                '"my tickets" / "status of my request" and you have customer_id or phone.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'customer_id': {'type': 'integer', 'description': 'Customer user id if known'},
                    'phone': {'type': 'string', 'description': 'Customer phone if id unknown'},
                },
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'lookup_ticket',
            'description': (
                'Use when the user gives a specific ticket reference such as TKT-XXXXXXXX '
                'and wants status or details for that ticket only.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'ticket_id': {'type': 'string', 'description': 'Ticket ID e.g. TKT-A1B2C3D4'},
                },
                'required': ['ticket_id'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'create_or_get_customer',
            'description': (
                'Use when registering or matching a customer before opening a ticket. '
                'Call when you have at least contact_name and phone. Email optional on WhatsApp.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'contact_name': {'type': 'string'},
                    'phone': {'type': 'string'},
                    'email': {'type': 'string'},
                    'address': {'type': 'string'},
                },
                'required': ['contact_name', 'phone'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'create_support_ticket',
            'description': (
                'Create a support ticket when the user reports an issue — do not ask for permission first. '
                'Requires description, priority (High/Medium/Low), category_names, and customer identity. '
                'The system refuses duplicates: if an open ticket already matches this complaint, '
                'returns existing ticket_id instead of creating a new one.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'description': {'type': 'string', 'description': 'Problem description from the user'},
                    'category_names': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'All category names that apply (from list_ticket_categories)',
                    },
                    'category_name': {
                        'type': 'string',
                        'description': 'Optional single category if only one applies',
                    },
                    'priority': {
                        'type': 'string',
                        'enum': ['High', 'Medium', 'Low'],
                    },
                    'customer_id': {'type': 'integer'},
                    'contact_name': {'type': 'string'},
                    'phone': {'type': 'string'},
                    'email': {'type': 'string'},
                },
                'required': ['description', 'priority'],
            },
        },
    },
]


def tool_get_user_context(customer_id=None, phone=None, conversation=None, request=None, **_kwargs):
    """Return the full customer profile + all their tickets + all categories."""
    # No identifier at all — tell the model to ask for phone first.
    has_linked = conversation and getattr(conversation, 'customer_id', None)
    if not customer_id and not phone and not has_linked:
        categories = list(TicketCategory.objects.order_by('name').values('id', 'name'))
        return {
            'error': 'no_identifier',
            'message': (
                'No customer identifier provided. '
                'Ask the user for their phone number to retrieve their data.'
            ),
            'customer': None,
            'tickets': [],
            'ticket_count': 0,
            'available_categories': categories,
        }

    customers, tickets = tickets_for_contact(
        phone=phone,
        customer_id=customer_id,
        conversation=conversation,
    )

    # If still nothing, try the conversation's linked customer
    if not customers.exists() and not tickets.exists() and conversation and conversation.customer_id:
        customers, tickets = tickets_for_contact(customer_id=conversation.customer_id)

    primary = customers.first()
    if not primary and tickets.exists() and tickets.first().customer_id:
        primary = tickets.first().customer

    ticket_rows = list(tickets.prefetch_related('categories').select_related('customer'))
    categories = list(TicketCategory.objects.order_by('name').values('id', 'name'))

    return {
        'customer': _customer_payload(primary) if primary else None,
        'tickets': [
            {
                'ticket_id': t.ticket_id,
                'status': t.status,
                'priority': t.priority,
                'categories': t.categories_display,
                'description': t.description,
                'created_at': t.created_at.isoformat(),
                'detail_url': ticket_detail_url(t.ticket_id, request=request, for_customer=True),
            }
            for t in ticket_rows
        ],
        'ticket_count': len(ticket_rows),
        'available_categories': categories,
    }


def tool_search_customers(query='', **_kwargs):
    q = (query or '').strip()
    qs = User.objects.filter(role='Customer').order_by('first_name', 'last_name')
    if q:
        filters = (
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(phone__icontains=q)
            | Q(email__icontains=q)
        )
        parts = q.split()
        if len(parts) >= 2:
            filters |= Q(
                first_name__icontains=parts[0],
                last_name__icontains=' '.join(parts[1:]),
            )
            filters |= Q(
                first_name__icontains=parts[0],
                last_name__icontains=parts[-1],
            )
        key = phone_match_key(q)
        if key and len(key) >= 9:
            filters |= Q(phone__icontains=key)
        for part in parts:
            part_key = phone_match_key(part)
            if part_key and len(part_key) >= 9:
                filters |= Q(phone__icontains=part_key)
        qs = qs.filter(filters)
    rows = list(qs[:10])
    return {
        'customers': [_customer_payload(c) for c in rows],
        'count': len(rows),
    }


def tool_list_ticket_categories(**_kwargs):
    cats = list(TicketCategory.objects.order_by('name').values('id', 'name'))
    return {'categories': cats}


def tool_get_customer_tickets(customer_id=None, phone=None, conversation=None, request=None, **_kwargs):
    # No identifier at all — tell the model to ask for the phone number.
    has_linked = conversation and getattr(conversation, 'customer_id', None)
    if not customer_id and not phone and not has_linked:
        return {
            'error': 'no_identifier',
            'message': (
                'No customer identifier provided. '
                'Ask the user for their phone number before listing tickets.'
            ),
            'tickets': [],
            'count': 0,
        }

    customers, tickets = tickets_for_contact(
        phone=phone,
        customer_id=customer_id,
        conversation=conversation,
    )
    if not customers.exists() and not tickets.exists():
        return {
            'error': 'customer_not_found',
            'message': (
                'No customer account found for that phone number or ID. '
                'Ask the user to double-check their number, or offer to register them.'
            ),
            'tickets': [],
            'count': 0,
        }

    link_conversation_to_best_customer(
        conversation, phone=phone, customer_id=customer_id,
    )
    customers, tickets = tickets_for_contact(
        phone=phone,
        customer_id=customer_id,
        conversation=conversation,
    )
    primary = customers.first()
    if not primary and tickets.exists() and tickets.first().customer_id:
        primary = tickets.first().customer

    ticket_rows = list(tickets)
    return {
        'customer': _customer_payload(primary) if primary else None,
        'customers_matched': customers.count(),
        'tickets': [
            {
                'ticket_id': t.ticket_id,
                'detail_url': ticket_detail_url(t.ticket_id, request=request, for_customer=True),
                'status': t.status,
                'priority': t.priority,
                'categories': t.categories_display,
                'description': t.description[:200],
                'created_at': t.created_at.isoformat(),
                'customer_id': t.customer_id,
            }
            for t in ticket_rows
        ],
        'count': len(ticket_rows),
    }


def tool_lookup_ticket(ticket_id='', request=None, conversation=None, phone=None, **_kwargs):
    tid = (ticket_id or '').strip().upper()
    ticket = Ticket.objects.filter(ticket_id__iexact=tid).select_related(
        'customer',
    ).prefetch_related('categories').first()
    if not ticket:
        return {'error': f'Ticket {tid} not found.'}
    url = ticket_detail_url(ticket.ticket_id, request=request, for_customer=True)
    owner = ticket.customer
    owner_payload = _customer_payload(owner) if owner else None
    belongs_to_query_phone = customer_matches_phone(owner, phone) if phone and owner else None
    if owner and conversation:
        link_conversation_to_best_customer(
            conversation,
            phone=owner.phone,
            customer_id=owner.id,
        )
    return {
        'ticket_id': ticket.ticket_id,
        'detail_url': url,
        'status': ticket.status,
        'priority': ticket.priority,
        'categories': ticket.categories_display,
        'description': ticket.description,
        'customer': owner.display_name if owner else None,
        'customer_id': owner.id if owner else None,
        'customer_phone': owner.phone if owner else None,
        'owner': owner_payload,
        'belongs_to_query_phone': belongs_to_query_phone,
        'created_at': ticket.created_at.isoformat(),
    }


def tool_create_or_get_customer(contact_name='', phone='', email='', address='', conversation=None, **_kwargs):
    phone = (phone or '').strip()
    if not contact_name or not phone:
        return {'error': 'contact_name and phone are required.'}

    from core.phone_utils import normalize_kenya_phone as _norm
    normalized_phone = _norm(phone)
    if normalized_phone:
        phone = normalized_phone

    matches = list(customers_for_contact(phone=phone, conversation=conversation))
    if matches:
        existing = matches[0]
        if conversation:
            conversation.customer = existing
            conversation.save(update_fields=['customer', 'updated_at'])
        return {'created': False, 'customer': _customer_payload(existing)}

    email = _customer_email_fallback(phone, email)
    if not email:
        return {'error': 'Could not derive email for new customer.'}

    existing = User.objects.filter(email__iexact=email, role='Customer').first()
    if existing:
        if conversation:
            conversation.customer = existing
            conversation.save(update_fields=['customer', 'updated_at'])
        return {'created': False, 'customer': _customer_payload(existing)}

    user = create_customer_user(
        contact_name=contact_name.strip(),
        email=email,
        phone=phone,
        password=None,
        address=(address or '').strip(),
    )
    user.set_unusable_password()
    user.save(update_fields=['password'])

    if conversation:
        conversation.customer = user
        conversation.save(update_fields=['customer', 'updated_at'])
    return {'created': True, 'customer': _customer_payload(user)}


def _customer_has_recent_open_ticket(customer):
    """Return the most recent open ticket created in the last 24 hours, or None."""
    from django.utils import timezone
    from datetime import timedelta
    cutoff = timezone.now() - timedelta(hours=24)
    return (
        Ticket.objects.filter(
            customer=customer,
            status__in=('Open', 'In Progress', 'On Hold'),
            created_at__gte=cutoff,
        )
        .order_by('-created_at')
        .first()
    )


def tool_create_support_ticket(
    description='',
    category_name='',
    category_names=None,
    priority='Medium',
    customer_id=None,
    contact_name='',
    phone='',
    email='',
    conversation=None,
    channel='web',
    selected_category_ids=None,
    request=None,
    **_kwargs,
):
    if not description:
        return {'error': 'description is required.'}
    if priority not in dict(Ticket.PRIORITY):
        priority = 'Medium'

    # On web channel the customer must be signed in (linked to the conversation).
    # WhatsApp identifies by phone so no login is needed there.
    if channel == 'web':
        has_linked = conversation and getattr(conversation, 'customer_id', None)
        has_phone = bool((phone or '').strip())
        if not has_linked and not has_phone:
            return {
                'error': 'login_required',
                'message': (
                    'The user must be signed in to create a ticket. '
                    'Tell them to sign in at the portal login page using their phone number '
                    'as both their username and password, then come back to this chat.'
                ),
            }

    names = list(category_names or [])
    if category_name:
        names.insert(0, category_name)

    categories = resolve_categories(
        category_names=names,
        category_ids=selected_category_ids,
    )
    if not categories:
        # Do NOT auto-suggest. The user must choose. Return the available list so
        # the model can present it and ask the user to pick.
        available = list(TicketCategory.objects.order_by('name').values('id', 'name'))
        return {
            'error': 'category_required',
            'message': (
                'No category was selected. Present the available_categories list to the user '
                'and ask them to choose the one that best fits their issue. '
                'Do not guess or pick on their behalf.'
            ),
            'available_categories': available,
        }

    customer = _resolve_customer(
        customer_id=customer_id, phone=phone, conversation=conversation,
    )
    if not customer and contact_name and phone:
        result = tool_create_or_get_customer(
            contact_name=contact_name,
            phone=phone,
            email=email,
            conversation=conversation,
        )
        if result.get('error'):
            return result
        customer = User.objects.filter(pk=result['customer']['id'], role='Customer').first()

    if not customer and conversation and conversation.customer_id:
        customer = conversation.customer

    if not customer:
        return {
            'error': 'Customer required. Provide customer_id or contact_name+phone, or register the customer first.',
        }

    # Block if customer already has an open ticket created in the last 24 hours.
    recent_open = _customer_has_recent_open_ticket(customer)
    if recent_open:
        return {
            'error': 'recent_open_ticket',
            'message': (
                f'This customer already has an open ticket ({recent_open.ticket_id}) '
                f'created within the last 24 hours (status: {recent_open.status}). '
                'Tell them they cannot create a new ticket until it is resolved or closed, '
                'or until 24 hours have passed.'
            ),
            'existing_ticket_id': recent_open.ticket_id,
            'existing_status': recent_open.status,
            'existing_categories': recent_open.categories_display,
        }

    existing = find_matching_open_ticket(customer, categories, description)
    if existing:
        if conversation:
            conversation.customer = customer
            conversation.save(update_fields=['customer', 'updated_at'])
        return duplicate_ticket_response(existing)

    ticket = Ticket.objects.create(
        customer=customer,
        description=description.strip(),
        priority=priority,
        status='Open',
    )
    ticket.categories.set(categories)

    from core.notifications import notify_ticket_created
    notify_ticket_created(ticket, source='assistant')

    if conversation:
        from core.assistant.conversation import clear_conversation_category_ids
        conversation.customer = customer
        conversation.save(update_fields=['customer', 'updated_at'])
        clear_conversation_category_ids(conversation)

    cat_label = _categories_label(categories)
    url = ticket_detail_url(ticket.ticket_id, request=request, for_customer=True)
    return {
        'success': True,
        'ticket_id': ticket.ticket_id,
        'detail_url': url,
        'status': ticket.status,
        'priority': ticket.priority,
        'categories': cat_label,
        'category': cat_label,
        'customer': customer.display_name,
        'channel': channel,
        'message': (
            f'Support ticket {ticket.ticket_id} has been created. '
            f'View your ticket: {url} '
            f'Our team will follow up shortly.'
        ),
    }


TOOL_HANDLERS = {
    'get_user_context': tool_get_user_context,
    'search_customers': tool_search_customers,
    'list_ticket_categories': tool_list_ticket_categories,
    'get_customer_tickets': tool_get_customer_tickets,
    'lookup_ticket': tool_lookup_ticket,
    'create_or_get_customer': tool_create_or_get_customer,
    'create_support_ticket': tool_create_support_ticket,
}


def execute_tool(name, arguments, conversation=None, channel='web', selected_category_ids=None, request=None):
    """Run a tool and return a JSON-serializable dict."""
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return {'error': f'Unknown tool: {name}'}
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
    except json.JSONDecodeError:
        return {'error': 'Invalid tool arguments JSON.'}
    try:
        result = handler(
            **args,
            conversation=conversation,
            channel=channel,
            selected_category_ids=selected_category_ids,
            request=request,
        )
        return result
    except Exception as exc:
        return {'error': str(exc)}
