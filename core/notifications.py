"""Outbound SMS notifications (UjumbeSMS)."""

import logging

from django.contrib.auth import get_user_model

from core.models import Ticket, TicketAssignment
from core.phone_utils import normalize_kenya_phone
from core.sms_debug import sms_debug, sms_debug_ujumbe_config
from core.sms_report import SmsReport
from core.ticket_urls import ticket_detail_url
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


def _user_label(user):
    if not user:
        return 'Unknown user'
    name = f'{user.first_name} {user.last_name}'.strip()
    if name and name != '-':
        return f'{name} ({user.email})'
    return user.email or f'User #{user.pk}'


def _format_api_result(result):
    if not result:
        return 'No response from SMS API'
    if result.get('message'):
        return result['message']
    if result.get('error'):
        return str(result['error'])
    return 'SMS API returned failure'


def _sms_to_user(user, message, context_label, source):
    """Legacy bool helper — billing and other callers."""
    step = _sms_to_user_step(
        user, message, context_label, source,
        step_id='send', step_label=context_label,
    )
    return step['status'] == 'done'


def _sms_to_user_step(user, message, context_label, source, step_id, step_label):
    """Send one SMS; return a step dict for SmsReport."""
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
        return {
            'id': step_id,
            'label': step_label,
            'status': 'skipped',
            'detail': f'{_user_label(user)} has no phone number on file.',
            'error': 'Add a valid Kenyan mobile on the user profile (254… or 07…).',
        }

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
        return {
            'id': step_id,
            'label': step_label,
            'status': 'error',
            'detail': f'{_user_label(user)} — raw phone: {raw!r}',
            'error': 'Phone could not be normalized to 254XXXXXXXXX for UjumbeSMS.',
        }

    sms_debug(
        source,
        'sms_to_user_send',
        context=context_label,
        normalized_phone=phone,
        message_preview=message[:80] + ('…' if len(message) > 80 else ''),
    )
    result = send_sms(phone, message, source=source, context=context_label)
    ok = isinstance(result, dict) and result.get('ok')
    sms_debug(source, 'sms_to_user_done', context=context_label, success=ok)

    if ok:
        api_status = result.get('api_status') or {}
        if isinstance(result.get('data'), dict):
            api_status = api_status or result['data'].get('status') or {}
        api_desc = ''
        if isinstance(api_status, dict):
            api_desc = (api_status.get('description') or 'OK').strip()
        return {
            'id': step_id,
            'label': step_label,
            'status': 'done',
            'detail': f'Sent to {phone} ({_user_label(user)}). {api_desc}',
            'error': '',
        }

    err_msg = _format_api_result(result)
    api_status = result.get('api_status') if isinstance(result, dict) else None
    if isinstance(api_status, dict) and api_status.get('code'):
        err_msg = (
            f"UjumbeSMS {api_status.get('code')}: {api_status.get('description', '')}. "
            f'{err_msg}'
        ).strip()

    return {
        'id': step_id,
        'label': step_label,
        'status': 'error',
        'detail': f'Target {phone} ({_user_label(user)})',
        'error': err_msg,
    }


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


def build_ticket_created_customer_sms(ticket):
    customer = ticket.customer
    name = _first_name(customer, fallback='Customer').upper()
    return (
        f'Dear {name}, You have successfully opted into Metrolinks Solutions. '
        f'We appreciate your trust in choosing us for our services. '
        f'Your Ticket {ticket.ticket_id} has been created and is being handled.'
    )


def build_ticket_created_with_agent_sms(ticket, agent):
    """Combined creation + assignment message when agent is assigned at creation."""
    customer = ticket.customer
    name = _first_name(customer, fallback='there')
    agent_first = _first_name(agent, fallback='our team')
    agent_phone = (getattr(agent, 'phone', None) or '').strip()

    message = (
        f"Hi {name.upper()}, We've received your Ticket, and our agent "
        f'{agent_first.upper()} is here to help. '
    )
    if agent_phone:
        message += f'You can reach them directly at {agent_phone}. '
    message += (
        "We're working on resolving your issue as quickly as possible. "
        'Thank you for your patience and understanding.'
    )
    return message


def build_ticket_created_receptionist_sms(ticket):
    customer = ticket.customer
    customer_name = _first_name(customer, fallback='Unknown')
    customer_phone = customer.phone if customer else ''
    phone_part = f' ({customer_phone})' if customer_phone else ''
    return (
        f'New ticket {ticket.ticket_id} created by {customer_name}{phone_part}. '
        f'Categories: {ticket.categories_display}. '
        f'Priority: {ticket.priority}.'
    )


def notify_ticket_created(ticket, source='unknown', agent=None):
    """SMS customer and optionally agent when a ticket is logged. Returns SmsReport."""
    report = SmsReport(
        title=f'SMS notifications — ticket {ticket.ticket_id} created',
        event='ticket_created',
        ticket_id=ticket.ticket_id,
        source=source,
    )

    sms_debug(source, 'notify_ticket_created_start', ticket_id=ticket.ticket_id,
              with_agent=bool(agent))
    sms_debug_ujumbe_config(source)

    if not report.add_config_step(ujumbe_configured()):
        sms_debug(source, 'notify_ticket_created_skip', reason='ujumbe_not_configured')
        sms_debug(source, 'notify_ticket_created_end', ticket_id=ticket.ticket_id)
        return report

    ticket = _ticket_for_sms(ticket)

    report.add_step(
        'ticket_saved',
        'Ticket saved in database',
        'done',
        detail=f'Ticket {ticket.ticket_id} — customer id {ticket.customer_id or "none"}',
    )

    if agent:
        report.add_step(
            'assignment_saved',
            'Agent assignment saved',
            'done',
            detail=f'Assigned to {_user_label(agent)}',
        )
    else:
        report.add_step(
            'assignment_saved',
            'Agent assignment',
            'skipped',
            detail='No agent selected at creation — customer gets creation SMS only.',
        )

    if ticket.customer:
        if agent:
            customer_msg = build_ticket_created_with_agent_sms(ticket, agent)
            label = f'SMS customer — ticket created + assigned'
        else:
            customer_msg = build_ticket_created_customer_sms(ticket)
            label = f'SMS customer — ticket created'
        report.steps.append(_sms_to_user_step(
            ticket.customer, customer_msg, label, source,
            step_id='sms_customer', step_label=label,
        ))
    else:
        sms_debug(source, 'notify_ticket_created_skip_customer', reason='no_customer')
        report.add_step(
            'sms_customer',
            'SMS customer',
            'skipped',
            detail='Ticket has no linked customer.',
        )

    if agent:
        agent_label = 'SMS assigned agent'
        report.steps.append(_sms_to_user_step(
            agent,
            build_ticket_assigned_agent_sms(ticket, agent),
            agent_label,
            source,
            step_id='sms_agent',
            step_label=agent_label,
        ))
    else:
        report.add_step(
            'sms_agent',
            'SMS assigned agent',
            'skipped',
            detail='No agent assigned at creation.',
        )

    if source == 'assistant':
        User = get_user_model()
        receptionists = User.objects.filter(role='Receptionist').exclude(phone='')
        receptionist_msg = build_ticket_created_receptionist_sms(ticket)
        if receptionists.exists():
            for idx, receptionist in enumerate(receptionists, start=1):
                report.steps.append(_sms_to_user_step(
                    receptionist,
                    receptionist_msg,
                    f'Ticket {ticket.ticket_id} created (receptionist)',
                    source,
                    step_id=f'sms_receptionist_{idx}',
                    step_label=f'SMS receptionist #{idx}',
                ))
        else:
            report.add_step(
                'sms_receptionist',
                'SMS receptionists',
                'skipped',
                detail='No receptionists with phone numbers on file.',
            )
    else:
        sms_debug(source, 'notify_ticket_created_skip_receptionist', reason='not_from_assistant')

    sms_debug(source, 'notify_ticket_created_end', ticket_id=ticket.ticket_id)
    return report


def notify_ticket_assigned(ticket, agent, source='unknown', notify_customer=True):
    """SMS customer and assigned field agent. Returns SmsReport."""
    report = SmsReport(
        title=f'SMS notifications — ticket {ticket.ticket_id} assigned',
        event='ticket_assigned',
        ticket_id=ticket.ticket_id,
        source=source,
    )

    sms_debug(
        source,
        'notify_ticket_assigned_start',
        ticket_id=ticket.ticket_id,
        agent_id=getattr(agent, 'pk', None),
        agent_email=getattr(agent, 'email', None),
        agent_phone=getattr(agent, 'phone', None),
    )
    sms_debug_ujumbe_config(source)

    if not report.add_config_step(ujumbe_configured()):
        sms_debug(source, 'notify_ticket_assigned_skip', reason='ujumbe_not_configured')
        return report

    if not agent:
        sms_debug(source, 'notify_ticket_assigned_skip', reason='no_agent')
        report.add_step(
            'assignment_saved',
            'Agent assignment',
            'error',
            error='No agent provided for assignment notification.',
        )
        return report

    ticket = _ticket_for_sms(ticket)

    report.add_step(
        'assignment_saved',
        'Agent assignment saved in database',
        'done',
        detail=f'Assigned to {_user_label(agent)}',
    )

    if notify_customer:
        if ticket.customer:
            label = 'SMS customer — agent assigned'
            report.steps.append(_sms_to_user_step(
                ticket.customer,
                build_ticket_assigned_customer_sms(ticket, agent),
                label,
                source,
                step_id='sms_customer',
                step_label=label,
            ))
        else:
            sms_debug(source, 'notify_ticket_assigned_skip_customer', reason='no_customer')
            report.add_step(
                'sms_customer',
                'SMS customer',
                'skipped',
                detail='Ticket has no linked customer.',
            )
    else:
        sms_debug(source, 'notify_ticket_assigned_skip_customer',
                  reason='already_notified_at_creation')
        report.add_step(
            'sms_customer',
            'SMS customer',
            'skipped',
            detail='Customer already notified at ticket creation (combined message).',
        )

    agent_label = 'SMS assigned agent'
    report.steps.append(_sms_to_user_step(
        agent,
        build_ticket_assigned_agent_sms(ticket, agent),
        agent_label,
        source,
        step_id='sms_agent',
        step_label=agent_label,
    ))

    sms_debug(source, 'notify_ticket_assigned_end', ticket_id=ticket.ticket_id)
    return report


def assign_ticket_to_agent(ticket, agent, source='unknown', notify_customer=True):
    """Replace assignment for a ticket and notify customer + agent. Returns SmsReport."""
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
    report = notify_ticket_assigned(
        ticket, agent, source=source, notify_customer=notify_customer,
    )
    sms_debug(source, 'assign_ticket_to_agent_end', ticket_id=ticket.ticket_id)
    return report
