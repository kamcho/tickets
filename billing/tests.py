import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from billing.models import Invoice, MpesaPayment, Plan, Subscription
from billing.mpesa import parse_stk_callback
from billing.period import add_one_billing_month
from billing.services import apply_stk_callback

User = get_user_model()


SUCCESS_CALLBACK = {
    'Body': {
        'stkCallback': {
            'MerchantRequestID': 'mr-1',
            'CheckoutRequestID': 'ws_CO_1',
            'ResultCode': 0,
            'ResultDesc': 'The service request is processed successfully.',
            'CallbackMetadata': {
                'Item': [
                    {'Name': 'Amount', 'Value': 10.0},
                    {'Name': 'MpesaReceiptNumber', 'Value': 'ABC123XYZ'},
                    {'Name': 'TransactionDate', 'Value': 20260805120000},
                    {'Name': 'PhoneNumber', 'Value': 254712345678},
                ]
            },
        }
    }
}


class ParseCallbackTests(TestCase):
    def test_parse_success(self):
        parsed = parse_stk_callback(SUCCESS_CALLBACK)
        self.assertEqual(parsed['checkout_request_id'], 'ws_CO_1')
        self.assertEqual(parsed['mpesa_receipt_number'], 'ABC123XYZ')
        self.assertEqual(parsed['phone'], '254712345678')
        self.assertEqual(parsed['result_code'], 0)


class ApplyCallbackTests(TestCase):
    def setUp(self):
        self.payment = MpesaPayment.objects.create(
            phone='254712345678',
            amount=Decimal('10'),
            account_reference='TEST',
            merchant_request_id='mr-1',
            checkout_request_id='ws_CO_1',
            status=MpesaPayment.STATUS_PENDING,
        )

    def test_apply_success(self):
        payment, updated = apply_stk_callback(SUCCESS_CALLBACK)
        self.assertTrue(updated)
        self.assertEqual(payment.status, MpesaPayment.STATUS_SUCCESS)
        self.assertEqual(payment.mpesa_receipt_number, 'ABC123XYZ')

    def test_idempotent_success(self):
        apply_stk_callback(SUCCESS_CALLBACK)
        payment, updated = apply_stk_callback(SUCCESS_CALLBACK)
        self.assertFalse(updated)
        self.assertEqual(payment.status, MpesaPayment.STATUS_SUCCESS)

    def test_cancelled(self):
        body = {
            'Body': {
                'stkCallback': {
                    'MerchantRequestID': 'mr-1',
                    'CheckoutRequestID': 'ws_CO_1',
                    'ResultCode': 1032,
                    'ResultDesc': 'Request cancelled by user',
                }
            }
        }
        payment, updated = apply_stk_callback(body)
        self.assertTrue(updated)
        self.assertEqual(payment.status, MpesaPayment.STATUS_CANCELLED)


class SubscriptionOnCallbackTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='cust@example.com',
            password='x',
            first_name='Cust',
            last_name='Omer',
            phone='254712345678',
            role='Customer',
        )
        self.plan = Plan.objects.create(
            name='10 Mbps Home',
            speed_mbps=10,
            price=Decimal('2000.00'),
            is_active=True,
        )
        from django.utils import timezone
        from datetime import timedelta
        now = timezone.now()
        self.sub = Subscription.objects.create(
            customer=self.user,
            plan=self.plan,
            status=Subscription.STATUS_ACTIVE,
            started_at=now - timedelta(days=20),
            expires_at=now + timedelta(days=10),
        )
        self.invoice = Invoice.objects.create(
            subscription=self.sub,
            period_start=self.sub.started_at,
            period_end=self.sub.expires_at,
            amount_due=self.plan.price,
            amount_paid=0,
            status=Invoice.STATUS_ISSUED,
            due_at=self.sub.expires_at,
        )
        self.payment = MpesaPayment.objects.create(
            customer=self.user,
            phone='254712345678',
            amount=Decimal('2000'),
            account_reference='TEST',
            merchant_request_id='mr-1',
            checkout_request_id='ws_CO_1',
            status=MpesaPayment.STATUS_PENDING,
            subscription=self.sub,
            invoice=self.invoice,
        )

    def test_callback_extends_subscription_and_pays_invoice(self):
        body = {
            'Body': {
                'stkCallback': {
                    'MerchantRequestID': 'mr-1',
                    'CheckoutRequestID': 'ws_CO_1',
                    'ResultCode': 0,
                    'ResultDesc': 'ok',
                    'CallbackMetadata': {
                        'Item': [
                            {'Name': 'Amount', 'Value': 2000.0},
                            {'Name': 'MpesaReceiptNumber', 'Value': 'RCP999'},
                            {'Name': 'PhoneNumber', 'Value': 254712345678},
                        ]
                    },
                }
            }
        }
        old_expires = self.sub.expires_at
        payment, updated = apply_stk_callback(body)
        self.assertTrue(updated)
        self.sub.refresh_from_db()
        self.invoice.refresh_from_db()
        payment.refresh_from_db()

        self.assertEqual(payment.status, MpesaPayment.STATUS_SUCCESS)
        self.assertIsNotNone(payment.billing_applied_at)
        self.assertEqual(self.invoice.status, Invoice.STATUS_PAID)
        self.assertEqual(self.sub.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(self.sub.expires_at, add_one_billing_month(old_expires))
        self.assertEqual(self.sub.started_at, old_expires)

    def test_callback_billing_idempotent(self):
        body = {
            'Body': {
                'stkCallback': {
                    'MerchantRequestID': 'mr-1',
                    'CheckoutRequestID': 'ws_CO_1',
                    'ResultCode': 0,
                    'ResultDesc': 'ok',
                    'CallbackMetadata': {
                        'Item': [
                            {'Name': 'Amount', 'Value': 2000.0},
                            {'Name': 'MpesaReceiptNumber', 'Value': 'RCP999'},
                            {'Name': 'PhoneNumber', 'Value': 254712345678},
                        ]
                    },
                }
            }
        }
        apply_stk_callback(body)
        self.sub.refresh_from_db()
        expires_once = self.sub.expires_at
        apply_stk_callback(body)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.expires_at, expires_once)


class BillingSmsTests(TestCase):
    def setUp(self):
        from django.utils import timezone
        from datetime import timedelta

        self.user = User.objects.create_user(
            email='sms@example.com',
            password='x',
            first_name='Ada',
            phone='254712345678',
            role='Customer',
        )
        self.plan = Plan.objects.create(
            name='10 Mbps Home',
            speed_mbps=10,
            price=Decimal('2000.00'),
            is_active=True,
        )
        now = timezone.now()
        self.sub = Subscription.objects.create(
            customer=self.user,
            plan=self.plan,
            status=Subscription.STATUS_ACTIVE,
            started_at=now - timedelta(days=27),
            expires_at=now + timedelta(days=3),
        )
        self.invoice = Invoice.objects.create(
            subscription=self.sub,
            period_start=self.sub.started_at,
            period_end=self.sub.expires_at,
            amount_due=self.plan.price,
            amount_paid=0,
            status=Invoice.STATUS_ISSUED,
            due_at=self.sub.expires_at,
        )
        self.payment = MpesaPayment.objects.create(
            customer=self.user,
            phone='254712345678',
            amount=Decimal('2000'),
            account_reference='TEST',
            merchant_request_id='mr-sms',
            checkout_request_id='ws_CO_sms',
            status=MpesaPayment.STATUS_PENDING,
            subscription=self.sub,
            invoice=self.invoice,
        )

    @override_settings(UJUMBE_SMS_ENABLED=True, UJUMBE_SMS_API_KEY='k', UJUMBE_SMS_EMAIL='a@b.c')
    def test_payment_received_sms_on_callback(self):
        from unittest.mock import patch

        body = {
            'Body': {
                'stkCallback': {
                    'MerchantRequestID': 'mr-sms',
                    'CheckoutRequestID': 'ws_CO_sms',
                    'ResultCode': 0,
                    'ResultDesc': 'ok',
                    'CallbackMetadata': {
                        'Item': [
                            {'Name': 'Amount', 'Value': 2000.0},
                            {'Name': 'MpesaReceiptNumber', 'Value': 'RCP111'},
                            {'Name': 'PhoneNumber', 'Value': 254712345678},
                        ]
                    },
                }
            }
        }
        with patch('core.notifications.send_sms', return_value={'ok': True}) as mock_sms:
            apply_stk_callback(body)
            self.assertTrue(mock_sms.called)
            msg = mock_sms.call_args[0][1]
            self.assertIn('KES 2000', msg)
            self.assertIn('RCP111', msg)

    @override_settings(UJUMBE_SMS_ENABLED=True, UJUMBE_SMS_API_KEY='k', UJUMBE_SMS_EMAIL='a@b.c')
    def test_expiry_reminder_once(self):
        from unittest.mock import patch
        from billing.notifications import send_due_expiry_reminders

        with patch('core.notifications.send_sms', return_value={'ok': True}) as mock_sms:
            n = send_due_expiry_reminders(days=3)
            self.assertEqual(n, 1)
            self.assertTrue(mock_sms.called)
            self.assertIn('expires', mock_sms.call_args[0][1].lower())

            n2 = send_due_expiry_reminders(days=3)
            self.assertEqual(n2, 0)
            self.assertEqual(mock_sms.call_count, 1)

        self.sub.refresh_from_db()
        self.assertEqual(self.sub.expiry_reminder_for, self.sub.expires_at)


@override_settings(
    ROOT_URLCONF='core.urls',
    DEFAULT_HOST='default',
)
class CallbackEndpointTests(TestCase):
    def setUp(self):
        MpesaPayment.objects.create(
            phone='254712345678',
            amount=Decimal('10'),
            account_reference='TEST',
            merchant_request_id='mr-1',
            checkout_request_id='ws_CO_1',
            status=MpesaPayment.STATUS_PENDING,
        )
        self.client = Client()

    def test_callback_endpoint(self):
        url = reverse('billing_mpesa_stk_callback')
        resp = self.client.post(
            url,
            data=json.dumps(SUCCESS_CALLBACK),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        payment = MpesaPayment.objects.get(checkout_request_id='ws_CO_1')
        self.assertEqual(payment.status, MpesaPayment.STATUS_SUCCESS)
        self.assertEqual(payment.mpesa_receipt_number, 'ABC123XYZ')


class ManualAndPullPaymentTests(TestCase):
    def setUp(self):
        from datetime import timedelta
        from django.utils import timezone

        self.user = User.objects.create_user(
            email='pull@example.com',
            password='x',
            first_name='Pat',
            phone='254711111111',
            role='Customer',
        )
        self.plan = Plan.objects.create(
            name='10 Mbps Home',
            speed_mbps=10,
            price=Decimal('2000.00'),
            is_active=True,
        )
        now = timezone.now()
        self.sub = Subscription.objects.create(
            customer=self.user,
            plan=self.plan,
            status=Subscription.STATUS_ACTIVE,
            started_at=now - timedelta(days=20),
            expires_at=now + timedelta(days=10),
        )

    def test_record_manual_mpesa_renews(self):
        from billing.services import record_manual_payment

        old_expires = self.sub.expires_at
        payment = record_manual_payment(
            amount=Decimal('2000'),
            phone='0711111111',
            customer=self.user,
            mpesa_receipt='MANUALRCP1',
            is_cash=False,
            subscription=self.sub,
        )
        self.sub.refresh_from_db()
        self.assertEqual(payment.source, MpesaPayment.SOURCE_MANUAL)
        self.assertEqual(payment.status, MpesaPayment.STATUS_SUCCESS)
        self.assertIsNotNone(payment.billing_applied_at)
        self.assertEqual(self.sub.expires_at, add_one_billing_month(old_expires))

    def test_manual_duplicate_receipt_rejected(self):
        from billing.mpesa import MpesaError
        from billing.services import record_manual_payment

        record_manual_payment(
            amount=Decimal('2000'),
            phone='0711111111',
            customer=self.user,
            mpesa_receipt='DUPCODE99',
            subscription=self.sub,
        )
        with self.assertRaises(MpesaError):
            record_manual_payment(
                amount=Decimal('2000'),
                phone='0711111111',
                customer=self.user,
                mpesa_receipt='dupcode99',
                subscription=self.sub,
            )

    def test_pull_result_applies_billing(self):
        from billing.services import apply_transaction_status_result

        MpesaPayment.objects.create(
            source=MpesaPayment.SOURCE_PULL,
            customer=self.user,
            phone='254711111111',
            amount=Decimal('0'),
            account_reference='PULLRCP1',
            mpesa_receipt_number='PULLRCP1',
            originator_conversation_id='orig-conv-1',
            status=MpesaPayment.STATUS_PENDING,
            subscription=self.sub,
        )
        old_expires = self.sub.expires_at
        body = {
            'Result': {
                'OriginatorConversationID': 'orig-conv-1',
                'ConversationID': 'conv-1',
                'TransactionID': 'PULLRCP1',
                'ResultCode': 0,
                'ResultDesc': 'The service request is processed successfully.',
                'ResultParameters': {
                    'ResultParameter': [
                        {'Key': 'ReceiptNo', 'Value': 'PULLRCP1'},
                        {'Key': 'Amount', 'Value': 2000},
                        {'Key': 'DebitPartyName', 'Value': '254711111111 - PAT'},
                        {'Key': 'TransactionStatus', 'Value': 'Completed'},
                    ]
                },
            }
        }
        updated_payment, updated = apply_transaction_status_result(body)
        self.assertTrue(updated)
        updated_payment.refresh_from_db()
        self.sub.refresh_from_db()
        self.assertEqual(updated_payment.status, MpesaPayment.STATUS_SUCCESS)
        self.assertEqual(updated_payment.amount, Decimal('2000'))
        self.assertIsNotNone(updated_payment.billing_applied_at)
        self.assertEqual(self.sub.expires_at, add_one_billing_month(old_expires))

    def test_parse_transaction_status_result(self):
        from billing.mpesa import parse_transaction_status_result

        parsed = parse_transaction_status_result({
            'Result': {
                'OriginatorConversationID': 'o1',
                'ResultCode': 0,
                'ResultDesc': 'ok',
                'TransactionID': 'ABC',
                'ResultParameters': {
                    'ResultParameter': [
                        {'Key': 'Amount', 'Value': 100},
                        {'Key': 'DebitPartyName', 'Value': '254700000001 - X'},
                    ]
                },
            }
        })
        self.assertEqual(parsed['originator_conversation_id'], 'o1')
        self.assertEqual(parsed['amount'], 100)
        self.assertEqual(parsed['phone'], '254700000001')
