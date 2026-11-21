from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from billing.models import NetworkServiceAccount, Plan, Subscription
from billing.network_services import (
    get_or_create_account,
    schedule_disconnect,
    suspend_account,
)
from billing.period import add_one_billing_month
from core.models import NetworkRouter

User = get_user_model()


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    MIKROTIK_ENABLED=False,
    MIKROTIK_HOST='',
)
class NetworkAccountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='net@example.com',
            password='x',
            first_name='Net',
            phone='254722000111',
            role='Customer',
        )
        self.plan = Plan.objects.create(
            name='10 Mbps Home',
            speed_mbps=10,
            price=Decimal('2000.00'),
            mikrotik_profile='10Mbps',
            is_active=True,
        )
        now = timezone.now()
        self.sub = Subscription.objects.create(
            customer=self.user,
            plan=self.plan,
            status=Subscription.STATUS_ACTIVE,
            started_at=now,
            expires_at=add_one_billing_month(now),
        )
        self.router = NetworkRouter.objects.create(
            name='Tower A',
            api_host='10.0.0.1',
            api_user='billing',
            api_password='secret',
            api_ssl=True,
            is_default=True,
            is_active=True,
        )

    def test_get_or_create_uses_phone_username(self):
        account = get_or_create_account(self.user, subscription=self.sub)
        self.assertEqual(account.username, '254722000111')
        self.assertEqual(account.profile, '10Mbps')
        self.assertEqual(account.router_id, self.router.pk)

    def test_suspend_without_live_api_when_no_credentials(self):
        NetworkRouter.objects.all().delete()
        account = get_or_create_account(self.user, subscription=self.sub)
        result = suspend_account(account, reason='staff')
        account.refresh_from_db()
        self.assertTrue(account.disabled)
        self.assertEqual(result.get('error'), 'mikrotik_not_configured')

    def test_schedule_disconnect_stores_task_id(self):
        schedule_disconnect(self.sub)
        self.sub.refresh_from_db()
        self.assertTrue(self.sub.disconnect_task_id)

    @patch('billing.mikrotik._request')
    def test_mikrotik_uses_account_router(self, mock_req):
        from billing.mikrotik import ensure_ppp_secret, resolve_connection

        account = get_or_create_account(
            self.user, subscription=self.sub, router=self.router,
        )
        conn = resolve_connection(account=account)
        self.assertEqual(conn.host, '10.0.0.1')
        self.assertEqual(conn.source, 'db')

        mock_req.side_effect = [
            [],
            None,
            [{'.id': '*1', 'name': '254722000111', 'disabled': 'false'}],
        ]
        row = ensure_ppp_secret(
            username='254722000111',
            password='pass',
            profile='10Mbps',
            account=account,
        )
        self.assertEqual(row.get('name'), '254722000111')

    def test_second_router_assignment(self):
        tower_b = NetworkRouter.objects.create(
            name='Tower B',
            api_host='10.0.0.2',
            api_user='billing',
            api_password='secret2',
            is_active=True,
        )
        account = get_or_create_account(
            self.user, subscription=self.sub, router=tower_b,
        )
        self.assertEqual(account.router_id, tower_b.pk)


@override_settings(
    ROOT_URLCONF='core.urls',
    DEFAULT_HOST='default',
    CELERY_TASK_ALWAYS_EAGER=True,
    MIKROTIK_ENABLED=False,
)
class NetworkApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            email='admin@example.com',
            password='x',
            role='Admin',
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            email='c2@example.com',
            password='x',
            phone='254733000222',
            role='Customer',
        )
        self.account = NetworkServiceAccount.objects.create(
            customer=self.customer,
            username='254733000222',
            profile='10Mbps',
            password='x',
        )
        self.client = Client()
        self.client.force_login(self.staff)

    def test_suspend_endpoint(self):
        url = reverse('billing_network_account_suspend', kwargs={'pk': self.account.pk})
        resp = self.client.post(url)
        self.assertIn(resp.status_code, (200, 502))
        data = resp.json()
        self.assertEqual(data['username'], '254733000222')
        self.account.refresh_from_db()
        self.assertTrue(self.account.disabled)

    def test_status_endpoint(self):
        url = reverse('billing_network_account_status', kwargs={'pk': self.account.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['username'], '254733000222')
