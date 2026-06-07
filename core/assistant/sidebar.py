"""Sidebar payload for the web assistant (tickets + current selection)."""

from core.customer_lookup import (
    customers_for_contact,
    link_conversation_to_best_customer,
    primary_customer,
    tickets_for_contact,
)
from core.models import Ticket
from core.ticket_urls import ticket_detail_url





def serialize_ticket(ticket, highlight=False, request=None):

    return {

        'ticket_id': ticket.ticket_id,

        'status': ticket.status,

        'priority': ticket.priority,

        'categories': ticket.categories_display,

        'category': ticket.categories_display,

        'description': (ticket.description or '')[:120],

        'created_at': ticket.created_at.isoformat(),

        'detail_url': ticket_detail_url(ticket.ticket_id, request=request, for_customer=True),

        'highlight': highlight,

    }





def build_sidebar_payload(conversation, current_ticket_id=None, request=None):

    link_conversation_to_best_customer(conversation)
    customers = customers_for_contact(conversation=conversation)
    customer = primary_customer(customers, conversation)

    tickets = []
    current_ticket = None

    if customers.exists():
        _, ticket_qs = tickets_for_contact(conversation=conversation, limit=20)
        ticket_rows = list(ticket_qs)

        if current_ticket_id:
            for t in ticket_rows:
                if t.ticket_id == current_ticket_id:
                    current_ticket = t
                    break
        if not current_ticket and ticket_rows:
            current_ticket = ticket_rows[0]
            current_ticket_id = current_ticket.ticket_id

        for t in ticket_rows:
            entry = serialize_ticket(
                t,
                highlight=current_ticket_id and t.ticket_id == current_ticket_id,
                request=request,
            )
            tickets.append(entry)



    customer_info = None

    if customer:

        customer_info = {

            'id': customer.id,

            'name': customer.display_name,

            'phone': customer.phone,

            'email': customer.email,

        }



    return {

        'customer': customer_info,

        'tickets': tickets,

        'current_ticket': (

            serialize_ticket(current_ticket, highlight=True, request=request) if current_ticket else None

        ),

    }





def sidebar_event(conversation, current_ticket_id=None, request=None):
    payload = build_sidebar_payload(
        conversation, current_ticket_id=current_ticket_id, request=request,
    )

    return {'event': 'sidebar', **payload}





def ticket_id_from_tool_result(tool_name, result):

    if not result or result.get('error'):

        return None

    if tool_name == 'create_support_ticket' and result.get('success'):

        return result.get('ticket_id')

    if tool_name == 'lookup_ticket' and result.get('ticket_id'):

        return result.get('ticket_id')

    return None

