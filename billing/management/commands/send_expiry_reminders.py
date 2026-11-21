from django.core.management.base import BaseCommand

from billing.notifications import send_due_expiry_reminders


class Command(BaseCommand):
    help = (
        'SMS customers whose active subscription expires within N days '
        '(default 3). Safe to run hourly/daily — one SMS per expiry period.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=3,
            help='Remind if expires_at is within this many days (default 3)',
        )

    def handle(self, *args, **options):
        sent = send_due_expiry_reminders(days=options['days'])
        self.stdout.write(self.style.SUCCESS(f'Sent {sent} expiry reminder SMS.'))
