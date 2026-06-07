"""Absolute URLs for ticket detail pages (SMS, flash messages, assistant)."""

from django.conf import settings
from django.urls import reverse
from django.utils.html import format_html


def site_base_url(request=None):
    if request is not None:
        return request.build_absolute_uri('/').rstrip('/')
    base = getattr(settings, 'SITE_BASE_URL', '').strip()
    if base:
        return base.rstrip('/')
    if not getattr(settings, 'DEBUG', True):
        return 'https://tickets.metrolinkssolutionltd.co.ke'
    return 'http://127.0.0.1:8000'


def ticket_detail_url(ticket_id, *, request=None, for_customer=True):
    """Full URL to staff (/tickets/…) or customer portal (/portal/tickets/…) detail."""
    name = 'portal_ticket_detail' if for_customer else 'ticket_detail'
    path = reverse(name, kwargs={'ticket_id': ticket_id})
    return f'{site_base_url(request)}{path}'


def ticket_detail_link_html(ticket_id, *, request=None, for_customer=True):
    url = ticket_detail_url(ticket_id, request=request, for_customer=for_customer)
    return format_html('<a href="{}">{}</a>', url, ticket_id)


def ticket_created_flash_message(
    ticket,
    request,
    *,
    for_customer=False,
    assigned_to=None,
    customer_name=None,
):
    link = ticket_detail_link_html(
        ticket.ticket_id, request=request, for_customer=for_customer,
    )
    if customer_name:
        msg = format_html(
            "Customer '{}' registered and ticket {} created successfully!",
            customer_name,
            link,
        )
    else:
        msg = format_html('Ticket {} created successfully!', link)
    if assigned_to:
        msg = format_html('{} Assigned to {}.', msg, assigned_to.email)
    return msg
