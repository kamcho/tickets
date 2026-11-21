from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Seed mock expenditure and M-Pesa income for the last 3 months'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete previously seeded mock rows (tagged) before inserting',
        )

    def handle(self, *args, **options):
        from decimal import Decimal
        import random
        import uuid
        from datetime import timedelta

        from django.utils import timezone

        from billing.models import Expenditure, MpesaPayment

        now = timezone.now()
        start = now - timedelta(days=90)
        rng = random.Random(42)

        MOCK_EXP_PREFIX = '[MOCK]'
        MOCK_INCOME_REF = 'MOCK-INCOME'

        if options['clear']:
            exp_deleted, _ = Expenditure.objects.filter(title__startswith=MOCK_EXP_PREFIX).delete()
            pay_deleted, _ = MpesaPayment.objects.filter(account_reference=MOCK_INCOME_REF).delete()
            self.stdout.write(self.style.WARNING(
                f'Cleared mock data: {exp_deleted} expenditures, {pay_deleted} payments'
            ))

        expense_catalog = [
            ('Tower site rent', 'Monthly rent for POP / tower compound', 'bank', (15000, 45000)),
            ('Electricity — POP', 'KPLC bill for power at access point', 'bank', (3500, 18000)),
            ('Fuel — generator', 'Diesel for backup generator', 'cash', (2000, 9000)),
            ('Fiber splice materials', 'Closures, sleeves, and drop cable', 'mpesa', (1500, 12000)),
            ('Radio / CPE stock', 'Customer premises equipment restock', 'bank', (8000, 55000)),
            ('Staff airtime', 'Field agent coordination airtime', 'mpesa', (500, 3000)),
            ('Vehicle fuel', 'Van fuel for installations', 'cash', (1500, 7000)),
            ('Office internet backup', 'Failover link subscription', 'mpesa', (2500, 6000)),
            ('Tools & PPE', 'Safety gear and installation tools', 'card', (1000, 8000)),
            ('Software / SaaS', 'Monitoring and billing tools', 'card', (1200, 9000)),
            ('Contractor — civil works', 'Ducting and pole work', 'cheque', (10000, 80000)),
            ('Office supplies', 'Stationery and consumables', 'cash', (300, 2500)),
        ]

        income_plans = [
            (Decimal('2500.00'), 'Home 10Mbps'),
            (Decimal('4500.00'), 'Home 20Mbps'),
            (Decimal('6500.00'), 'Business 50Mbps'),
            (Decimal('1500.00'), 'Hotspot monthly'),
            (Decimal('9000.00'), 'SME dedicated'),
        ]

        methods = [c[0] for c in Expenditure.METHOD_CHOICES]

        expenditures = []
        # ~2–4 expenses per week over 90 days ≈ 30–50 records
        day = start
        while day <= now:
            if rng.random() < 0.45:  # some days have spending
                n = rng.randint(1, 3)
                for _ in range(n):
                    title, desc, method, (lo, hi) = rng.choice(expense_catalog)
                    amount = Decimal(rng.randint(lo, hi))
                    occurred = day.replace(
                        hour=rng.randint(8, 18),
                        minute=rng.randint(0, 59),
                        second=rng.randint(0, 59),
                        microsecond=0,
                    )
                    if occurred > now:
                        occurred = now - timedelta(minutes=rng.randint(5, 180))
                    expenditures.append(Expenditure(
                        title=f'{MOCK_EXP_PREFIX} {title}',
                        description=desc,
                        amount=amount,
                        payment_method=method if method in methods else Expenditure.METHOD_OTHER,
                        occurred_at=occurred,
                    ))
            day += timedelta(days=1)

        Expenditure.objects.bulk_create(expenditures)

        payments = []
        day = start
        while day <= now:
            # income most weekdays, lighter weekends
            weekday = day.weekday()
            chance = 0.75 if weekday < 5 else 0.35
            if rng.random() < chance:
                count = rng.randint(1, 5 if weekday < 5 else 2)
                for _ in range(count):
                    amount, plan = rng.choice(income_plans)
                    # occasional custom top-up
                    if rng.random() < 0.12:
                        amount = Decimal(rng.randint(500, 20000))
                        plan = 'Custom payment'
                    occurred = day.replace(
                        hour=rng.randint(7, 21),
                        minute=rng.randint(0, 59),
                        second=rng.randint(0, 59),
                        microsecond=0,
                    )
                    if occurred > now:
                        occurred = now - timedelta(minutes=rng.randint(5, 240))
                    phone_suffix = rng.randint(100000, 999999)
                    receipt = f'MK{uuid.uuid4().hex[:8].upper()}'
                    payments.append(MpesaPayment(
                        phone=f'2547{phone_suffix}',
                        amount=amount,
                        account_reference=MOCK_INCOME_REF,
                        description=f'{plan} subscription',
                        merchant_request_id=f'mock-mer-{uuid.uuid4().hex[:10]}',
                        checkout_request_id=f'mock-chk-{uuid.uuid4().hex[:10]}',
                        mpesa_receipt_number=receipt,
                        status=MpesaPayment.STATUS_SUCCESS,
                        result_code=0,
                        result_desc='The service request is processed successfully.',
                        created_at=occurred,
                        updated_at=occurred,
                        completed_at=occurred,
                    ))
            day += timedelta(days=1)

        MpesaPayment.objects.bulk_create(payments)
        # auto_now_add forces created_at=now on insert; align with seeded completed_at
        from django.db.models import F
        MpesaPayment.objects.filter(
            account_reference=MOCK_INCOME_REF,
            completed_at__isnull=False,
        ).update(created_at=F('completed_at'), updated_at=F('completed_at'))

        exp_total = sum((e.amount for e in expenditures), Decimal('0'))
        inc_total = sum((p.amount for p in payments), Decimal('0'))

        self.stdout.write(self.style.SUCCESS(
            f'Seeded {len(expenditures)} expenditures (KES {exp_total:,.2f}) '
            f'and {len(payments)} income payments (KES {inc_total:,.2f}) '
            f'from {start.date()} to {now.date()}.'
        ))
        self.stdout.write('Re-run with --clear to replace mock rows.')
