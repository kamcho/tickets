from django.core.management.base import BaseCommand

from billing.models import Plan


# Test packages: KES 2000 @ 10 Mbps, +500 per +5 Mbps up to 40 Mbps
TEST_PLANS = [
    (10, 2000),
    (15, 2500),
    (20, 3000),
    (25, 3500),
    (30, 4000),
    (35, 4500),
    (40, 5000),
]


class Command(BaseCommand):
    help = 'Seed test ISP plans (10–40 Mbps pricing ladder)'

    def handle(self, *args, **options):
        created = 0
        updated = 0
        for speed, price in TEST_PLANS:
            name = f'{speed} Mbps Home'
            obj, was_created = Plan.objects.update_or_create(
                speed_mbps=speed,
                defaults={
                    'name': name,
                    'price': price,
                    'mikrotik_profile': f'{speed}Mbps',
                    'is_active': True,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
            self.stdout.write(f'  {obj.name}: KES {obj.price}')

        self.stdout.write(self.style.SUCCESS(
            f'Done. Created {created}, updated {updated} plans.'
        ))
