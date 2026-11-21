from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from billing.models import Invoice, Subscription
from billing.period import add_one_billing_month
from billing.services import mark_expired_subscriptions


class Command(BaseCommand):
    help = (
        'Mark expired subscriptions (expires_at passed) and optionally '
        'issue renewal invoices for active subs nearing expiry.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--issue-renewals',
            action='store_true',
            help='Create next-period invoices for active subscriptions nearing expiry',
        )
        parser.add_argument(
            '--within-hours',
            type=int,
            default=24,
            help='Only issue renewals if expires_at is within this many hours (default 24)',
        )

    def handle(self, *args, **options):
        now = timezone.now()
        n_sub, n_inv = mark_expired_subscriptions(now=now)
        self.stdout.write(f'Marked {n_sub} subscriptions expired, {n_inv} invoices overdue.')

        if not options['issue_renewals']:
            return

        within = timedelta(hours=options['within_hours'])
        window_end = now + within
        issued = 0
        for sub in Subscription.objects.filter(
            status=Subscription.STATUS_ACTIVE,
            expires_at__lte=window_end,
            expires_at__gt=now,
        ).select_related('plan'):
            exists = Invoice.objects.filter(
                subscription=sub,
                period_end=sub.expires_at,
                status__in=[
                    Invoice.STATUS_ISSUED,
                    Invoice.STATUS_PARTIAL,
                    Invoice.STATUS_PAID,
                    Invoice.STATUS_OVERDUE,
                ],
            ).exists()
            if exists:
                continue
            next_end = add_one_billing_month(sub.expires_at)
            Invoice.objects.create(
                subscription=sub,
                period_start=sub.expires_at,
                period_end=next_end,
                amount_due=sub.plan.price,
                amount_paid=0,
                status=Invoice.STATUS_ISSUED,
                due_at=sub.expires_at,
            )
            issued += 1

        self.stdout.write(self.style.SUCCESS(f'Issued {issued} renewal invoices.'))
