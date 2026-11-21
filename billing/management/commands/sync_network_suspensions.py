from django.core.management.base import BaseCommand
from django.utils import timezone

from billing.models import NetworkServiceAccount, Subscription
from billing.network_services import on_subscription_expired, suspend_account


class Command(BaseCommand):
    help = (
        'Safety net: suspend PPPoE for expired subscriptions / disabled accounts '
        'that may have missed the Celery ETA disconnect.'
    )

    def handle(self, *args, **options):
        now = timezone.now()
        n = 0
        for sub in Subscription.objects.filter(
            status=Subscription.STATUS_EXPIRED,
            expires_at__lte=now,
        ).select_related('customer', 'plan'):
            account = NetworkServiceAccount.objects.filter(customer=sub.customer).first()
            if account and not account.disabled:
                suspend_account(account, reason='expire')
                n += 1
            elif not account:
                on_subscription_expired(sub, reason='expire')
                n += 1
        self.stdout.write(self.style.SUCCESS(f'Synced {n} network suspensions.'))
