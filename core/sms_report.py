"""Structured SMS activity reports for staff UI (modal + copy-to-clipboard)."""
from datetime import datetime, timezone

from django.conf import settings


def _config_detail():
    enabled = getattr(settings, 'UJUMBE_SMS_ENABLED', False)
    has_key = bool(getattr(settings, 'UJUMBE_SMS_API_KEY', ''))
    has_email = bool(getattr(settings, 'UJUMBE_SMS_EMAIL', ''))
    sender = getattr(settings, 'UJUMBE_SMS_SENDER_ID', '')
    base = getattr(settings, 'UJUMBE_SMS_BASE_URL', '')
    return (
        f'UJUMBE_SMS_ENABLED={enabled}, has_api_key={has_key}, '
        f'has_email={has_email}, sender={sender!r}, base_url={base!r}'
    )


def config_error_message():
    return (
        'UjumbeSMS is not configured. Set UJUMBE_SMS_ENABLED=True, '
        'UJUMBE_SMS_API_KEY, and UJUMBE_SMS_EMAIL in the server environment.'
    )


class SmsReport:
    """Collects pipeline steps for one ticket SMS event."""

    def __init__(self, title='', event='', ticket_id='', source=''):
        self.title = title
        self.event = event
        self.ticket_id = ticket_id
        self.source = source
        self.steps = []
        self.started_at = datetime.now(timezone.utc).isoformat()

    def add_step(self, step_id, label, status, detail='', error=''):
        self.steps.append({
            'id': step_id,
            'label': label,
            'status': status,
            'detail': detail or '',
            'error': error or '',
        })
        return self

    def add_config_step(self, configured):
        email = getattr(settings, 'UJUMBE_SMS_EMAIL', '') or ''
        masked_email = email
        if configured:
            self.add_step(
                'config',
                'Check UjumbeSMS configuration',
                'done',
                detail=_config_detail() + f' login_email={email!r}',
            )
        else:
            msg = config_error_message()
            self.add_step(
                'config',
                'Check UjumbeSMS configuration',
                'error',
                detail=_config_detail() + (f' login_email={email!r}' if email else ''),
                error=msg,
            )
        return configured

    @property
    def overall(self):
        statuses = [s['status'] for s in self.steps]
        if any(s == 'error' for s in statuses):
            if any(s == 'done' for s in statuses):
                return 'partial'
            return 'failed'
        if statuses and all(s == 'skipped' for s in statuses):
            return 'skipped'
        if any(s == 'skipped' for s in statuses):
            return 'partial'
        return 'success'

    def to_copy_text(self):
        lines = [
            self.title,
            f'Ticket: {self.ticket_id or "—"}',
            f'Event: {self.event}',
            f'Source: {self.source}',
            f'Started: {self.started_at}',
            f'Overall: {self.overall.upper()}',
            '',
            'Steps:',
        ]
        for i, step in enumerate(self.steps, 1):
            lines.append(f"{i}. [{step['status'].upper()}] {step['label']}")
            if step.get('detail'):
                lines.append(f"   Detail: {step['detail']}")
            if step.get('error'):
                lines.append(f"   Error: {step['error']}")
        lines.append('')
        lines.append('— Metrolinks ticket SMS report')
        return '\n'.join(lines)

    def to_dict(self):
        return {
            'title': self.title,
            'event': self.event,
            'ticket_id': self.ticket_id,
            'source': self.source,
            'started_at': self.started_at,
            'overall': self.overall,
            'steps': self.steps,
            'copy_text': self.to_copy_text(),
            'auto_open': self.overall in ('failed', 'partial'),
        }


def stash_sms_report(request, report):
    """Store report in session for the next page load (modal)."""
    if not report or not getattr(request, 'session', None):
        return
    if not report.steps:
        return
    request.session['sms_activity_report'] = report.to_dict()
    request.session.modified = True
