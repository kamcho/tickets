"""Plain-text replies when OpenAI is unavailable after tools already ran."""
from core.ticket_urls import ticket_detail_url


def _ticket_block(ticket, request=None):
    tid = ticket.get('ticket_id', '')
    url = ticket.get('detail_url') or ticket_detail_url(tid, request=request, for_customer=True)
    lines = [
        f'Ticket — {tid}',
        f'Link: {url}',
        f"Status: {ticket.get('status', '—')}",
        f"Priority: {ticket.get('priority', '—')}",
    ]
    categories = ticket.get('categories') or ticket.get('category')
    if categories:
        lines.append(f'Categories: {categories}')
    desc = (ticket.get('description') or '').strip()
    if desc:
        lines.append(f'Issue: {desc[:200]}')
    return '\n'.join(lines)


def compose_fallback_reply(tool_results, request=None):
    """
    Build a customer-facing reply from tool output (no LLM).

    tool_results: list of (tool_name, result_dict)
    """
    if not tool_results:
        return None

    for name, result in reversed(tool_results):
        if not result or result.get('error'):
            continue

        if name == 'get_customer_tickets':
            tickets = result.get('tickets') or []
            open_count = sum(1 for t in tickets if t.get('status') == 'Open')
            if not tickets:
                return (
                    'You do not have any tickets on file yet. '
                    'Tell me what you need help with and I can open one for you.'
                )
            intro = (
                f'You have {len(tickets)} ticket(s) on file'
                f' ({open_count} open).'
            )
            blocks = [_ticket_block(t, request=request) for t in tickets]
            return intro + '\n\n' + '\n\n'.join(blocks)

        if name == 'lookup_ticket':
            block = _ticket_block(result, request=request)
            return f'Here is your ticket:\n\n{block}'

        if name == 'create_support_ticket' and result.get('success'):
            tid = result.get('ticket_id', '')
            url = result.get('detail_url') or ticket_detail_url(tid, request=request, for_customer=True)
            return (
                f'Your support ticket {tid} has been created.\n'
                f'View it here: {url}\n'
                'Our team will follow up shortly.'
            )

        if name == 'search_customers':
            customers = result.get('customers') or []
            if len(customers) == 1:
                c = customers[0]
                return f"I found your account: {c.get('contact_name')} ({c.get('phone')})."
            if customers:
                names = ', '.join(c.get('contact_name', '') for c in customers[:3])
                return f'I found {len(customers)} matching customer record(s): {names}.'

    return None
