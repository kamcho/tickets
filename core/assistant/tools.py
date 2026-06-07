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


def _resolve_customer(customer_id=None, phone=None):
    if customer_id:
        return User.objects.filter(pk=customer_id, role='Customer').first()
    key = phone_match_key(phone)
    if not key:
        return None
    return User.objects.filter(role='Customer').filter(
        Q(phone__icontains=key)
    ).first()


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


def tool_search_customers(query='', **_kwargs):
    q = (query or '').strip()
    qs = User.objects.filter(role='Customer').order_by('first_name', 'last_name')
    if q:
        qs = qs.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(phone__icontains=q)
            | Q(email__icontains=q)
        )
    rows = list(qs[:10])
    return {
        'customers': [_customer_payload(c) for c in rows],
        'count': len(rows),
    }


def tool_list_ticket_categories(**_kwargs):
    cats = list(TicketCategory.objects.order_by('name').values('id', 'name'))
    return {'categories': cats}


def tool_get_customer_tickets(customer_id=None, phone=None, **_kwargs):
    customer = _resolve_customer(customer_id=customer_id, phone=phone)
    if not customer:
        return {'error': 'Customer not found.', 'tickets': []}
    tickets = Ticket.objects.filter(customer=customer).prefetch_related(
        'categories',
    ).order_by('-created_at')[:15]
    return {
        'customer': _customer_payload(customer),
        'tickets': [
            {
                'ticket_id': t.ticket_id,
                'status': t.status,
                'priority': t.priority,
                'categories': t.categories_display,
                'description': t.description[:200],
                'created_at': t.created_at.isoformat(),
            }
            for t in tickets
        ],
    }


def tool_lookup_ticket(ticket_id='', **_kwargs):
    tid = (ticket_id or '').strip().upper()
    ticket = Ticket.objects.filter(ticket_id__iexact=tid).select_related(
        'customer',
    ).prefetch_related('categories').first()
    if not ticket:
        return {'error': f'Ticket {tid} not found.'}
    url = ticket_detail_url(ticket.ticket_id, for_customer=True)
    return {
        'ticket_id': ticket.ticket_id,
        'detail_url': url,
        'status': ticket.status,
        'priority': ticket.priority,
        'categories': ticket.categories_display,
        'description': ticket.description,
        'customer': ticket.customer.display_name if ticket.customer else None,
        'created_at': ticket.created_at.isoformat(),
    }


def tool_create_or_get_customer(contact_name='', phone='', email='', address='', conversation=None, **_kwargs):
    phone = (phone or '').strip()
    if not contact_name or not phone:
        return {'error': 'contact_name and phone are required.'}

    existing = _resolve_customer(phone=phone)
    if existing:
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
    **_kwargs,
):
    if not description:
        return {'error': 'description is required.'}
    if priority not in dict(Ticket.PRIORITY):
        priority = 'Medium'

    names = list(category_names or [])
    if category_name:
        names.insert(0, category_name)

    categories = resolve_categories(
        category_names=names,
        category_ids=selected_category_ids,
    )
    if not categories:
        categories = resolve_categories(
            category_ids=suggest_category_ids(description),
        )
    if not categories:
        return {
            'error': (
                'At least one complaint category is required. '
                'Use list_ticket_categories or pass category_names that match the issue.'
            ),
        }

    customer = _resolve_customer(customer_id=customer_id, phone=phone)
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
    url = ticket_detail_url(ticket.ticket_id, for_customer=True)
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
    'search_customers': tool_search_customers,
    'list_ticket_categories': tool_list_ticket_categories,
    'get_customer_tickets': tool_get_customer_tickets,
    'lookup_ticket': tool_lookup_ticket,
    'create_or_get_customer': tool_create_or_get_customer,
    'create_support_ticket': tool_create_support_ticket,
}


def execute_tool(name, arguments, conversation=None, channel='web', selected_category_ids=None):
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
        )
        return result
    except Exception as exc:
        return {'error': str(exc)}
