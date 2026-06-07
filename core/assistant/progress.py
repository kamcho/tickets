"""Human-readable labels for assistant progress steps."""

TOOL_STEP_LABELS = {
    'search_customers': 'Getting customer info',
    'list_ticket_categories': 'Loading support categories',
    'get_customer_tickets': 'Fetching your tickets',
    'lookup_ticket': 'Looking up ticket',
    'create_or_get_customer': 'Saving customer details',
    'create_support_ticket': 'Creating support ticket',
}

STEP_THINKING = ('thinking', 'Understanding your request')
STEP_COMPOSE = ('compose', 'Preparing your reply')


def tool_step_label(tool_name):
    return TOOL_STEP_LABELS.get(
        tool_name,
        tool_name.replace('_', ' ').strip().title() if tool_name else 'Working',
    )


def progress_event(step_id, label, status):
    """status: pending | active | done | error"""
    return {
        'event': 'step',
        'id': step_id,
        'label': label,
        'status': status,
    }


def done_event(reply, sidebar=None):
    event = {'event': 'done', 'reply': reply}
    if sidebar:
        event['sidebar'] = sidebar
    return event


def error_event(message):
    return {'event': 'error', 'message': message}
