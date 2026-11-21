"""Ensure default ISP vendor exists and backfill vendor FKs (safe to re-run)."""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import (
    Vendor, MyUser, Ticket, TicketCategory, NetworkRouter,
)
from billing.models import Plan, Expenditure


class Command(BaseCommand):
    help = 'Create default vendor and assign orphan rows (multi-ISP v1).'

    def handle(self, *args, **options):
        slug = settings.DEFAULT_VENDOR_SLUG
        with transaction.atomic():
            vendor, created = Vendor.objects.get_or_create(
                slug=slug,
                defaults={
                    'name': 'Metrolinks Solution Ltd',
                    'phone_primary': getattr(settings, 'COMPANY_PHONE_PRIMARY', ''),
                    'phone_secondary': getattr(settings, 'COMPANY_PHONE_SECONDARY', ''),
                    'email': getattr(settings, 'COMPANY_EMAIL', ''),
                    'is_active': True,
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created vendor {vendor.name}'))

            # Tenant Admins must not be Django superusers (platform role is separate).
            MyUser.objects.filter(
                role='Admin', vendor__isnull=False, is_superuser=True,
            ).update(is_superuser=False)

            MyUser.objects.filter(vendor__isnull=True).exclude(
                is_superuser=True,
            ).update(vendor=vendor)
            Ticket.objects.filter(vendor__isnull=True).update(vendor=vendor)
            TicketCategory.objects.filter(vendor__isnull=True).update(vendor=vendor)
            NetworkRouter.objects.filter(vendor__isnull=True).update(vendor=vendor)
            Plan.objects.filter(vendor__isnull=True).update(vendor=vendor)
            Expenditure.objects.filter(vendor__isnull=True).update(vendor=vendor)

            # Tickets without vendor but with customer
            for t in Ticket.objects.filter(vendor__isnull=True).select_related('customer'):
                if t.customer and t.customer.vendor_id:
                    t.vendor_id = t.customer.vendor_id
                    t.save(update_fields=['vendor_id'])

        self.stdout.write(self.style.SUCCESS(f'Default vendor "{slug}" backfill complete.'))