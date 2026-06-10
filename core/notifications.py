"""Outbound SMS notifications (UjumbeSMS)."""

import logging



from core.models import Ticket, TicketAssignment

from core.phone_utils import normalize_kenya_phone
from core.ticket_urls import ticket_detail_url

from core.sms_debug import sms_debug, sms_debug_ujumbe_config

from core.ujumbe_sms import send_sms, ujumbe_configured



logger = logging.getLogger(__name__)





def _ticket_for_sms(ticket):

    """Reload ticket with relations needed for message text."""

    return (

        Ticket.objects.filter(pk=ticket.pk)

        .select_related('customer')

        .prefetch_related('categories')

        .first()

        or ticket

    )





def _agent_display_name(agent):

    name = f'{agent.first_name} {agent.last_name}'.strip()

    if name and name != '-':

        return name

    return agent.email





def _first_name(user, fallback='there'):

    name = (getattr(user, 'first_name', None) or '').strip()

    if name and name != '-':

        return name

    return fallback





def _sms_to_user(user, message, context_label, source):

    sms_debug(

        source,

        'sms_to_user_start',

        context=context_label,

        user_id=getattr(user, 'pk', None),

        email=getattr(user, 'email', None),

        raw_phone=getattr(user, 'phone', None) if user else None,

    )

    if not user or not user.phone:

        sms_debug(source, 'sms_to_user_skip', context=context_label, reason='no_phone_on_file')

        logger.info('%s: no phone on file.', context_label)

        return False

    raw = user.phone

    phone = normalize_kenya_phone(raw)

    if not phone:

        sms_debug(

            source,

            'sms_to_user_skip',

            context=context_label,

            reason='normalize_failed',

            raw_phone=raw,

        )

        logger.warning(

            '%s: phone %r could not be normalized to 254XXXXXXXXX for UjumbeSMS.',

            context_label,

            raw,

        )

        return False

    sms_debug(

        source,

        'sms_to_user_send',

        context=context_label,

        normalized_phone=phone,

        message_preview=message[:80] + ('…' if len(message) > 80 else ''),

    )

    result = send_sms(phone, message, source=source, context=context_label)

    ok = result is not None

    sms_debug(source, 'sms_to_user_done', context=context_label, success=ok)

    return ok





def build_ticket_assigned_customer_sms(ticket, agent):

    customer = ticket.customer

    customer_first = _first_name(customer, fallback='there')

    agent_first = _first_name(agent, fallback='our team')

    agent_phone = (getattr(agent, 'phone', None) or '').strip()

    message = (
        f'Hi {customer_first}, '
        f"We've received your issue, and our agent {agent_first} is here to help. "
    )

    if agent_phone:

        message += f'You can reach them directly at {agent_phone}. '

    message += (
        "We're working on resolving your issue as quickly as possible. "
        'Thank you for your patience and understanding.'
    )

    return message





def build_ticket_assigned_agent_sms(ticket, agent):

    agent_name = _agent_display_name(agent)

    customer = ticket.customer

    customer_label = customer.display_name if customer else 'Customer'

    customer_phone = customer.phone if customer else ''

    url = ticket_detail_url(ticket.ticket_id, for_customer=False)
    return (
        f'Hello {agent_name}, you have been assigned ticket {ticket.ticket_id}. '
        f'Customer: {customer_label}'
        f'{f" ({customer_phone})" if customer_phone else ""}. '
        f'Priority: {ticket.priority}. Categories: {ticket.categories_display}. '
        f'View ticket: {url}'
    )





def notify_ticket_created(ticket, source='unknown'):

    """Hook when a ticket is logged. Customer SMS is sent on agent assignment."""

    sms_debug(source, 'notify_ticket_created_start', ticket_id=ticket.ticket_id)

    sms_debug(source, 'notify_ticket_created_end', ticket_id=ticket.ticket_id)





def notify_ticket_assigned(ticket, agent, source='unknown'):

    """SMS customer and assigned field agent."""

    sms_debug(

        source,

        'notify_ticket_assigned_start',

        ticket_id=ticket.ticket_id,

        agent_id=getattr(agent, 'pk', None),

        agent_email=getattr(agent, 'email', None),

        agent_phone=getattr(agent, 'phone', None),

    )

    sms_debug_ujumbe_config(source)

    if not ujumbe_configured():

        sms_debug(source, 'notify_ticket_assigned_skip', reason='ujumbe_not_configured')

        return

    if not agent:

        sms_debug(source, 'notify_ticket_assigned_skip', reason='no_agent')

        return

    ticket = _ticket_for_sms(ticket)

    if ticket.customer:

        _sms_to_user(

            ticket.customer,

            build_ticket_assigned_customer_sms(ticket, agent),

            f'Ticket {ticket.ticket_id} assigned (customer)',

            source,

        )

    else:

        sms_debug(source, 'notify_ticket_assigned_skip_customer', reason='no_customer')

    _sms_to_user(

        agent,

        build_ticket_assigned_agent_sms(ticket, agent),

        f'Ticket {ticket.ticket_id} assigned (agent)',

        source,

    )

    sms_debug(source, 'notify_ticket_assigned_end', ticket_id=ticket.ticket_id)





def assign_ticket_to_agent(ticket, agent, source='unknown'):

    """Replace assignment for a ticket and notify customer + agent."""

    sms_debug(

        source,

        'assign_ticket_to_agent_start',

        ticket_id=ticket.ticket_id,

        agent_id=agent.pk,

        agent_email=agent.email,

    )

    TicketAssignment.objects.filter(ticket=ticket).delete()

    TicketAssignment.objects.create(ticket=ticket, assigned_to=agent)

    sms_debug(source, 'assign_ticket_to_agent_db_saved', ticket_id=ticket.ticket_id)

    notify_ticket_assigned(ticket, agent, source=source)

    sms_debug(source, 'assign_ticket_to_agent_end', ticket_id=ticket.ticket_id)

    return agent

