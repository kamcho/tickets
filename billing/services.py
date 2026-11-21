"""Apply STK responses and callbacks to MpesaPayment rows; renew subscriptions."""
import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from billing.models import MpesaPayment
from billing.mpesa import (
    MpesaError,
    initiate_stk_push,
    parse_stk_callback,
    parse_transaction_status_result,
    query_transaction_status,
)
from core.phone_utils import normalize_kenya_phone

logger = logging.getLogger(__name__)


def _existing_success_by_receipt(receipt):
    receipt = (receipt or '').strip().upper()
    if not receipt:
        return None
    return (
        MpesaPayment.objects.filter(
            mpesa_receipt_number__iexact=receipt,
            status=MpesaPayment.STATUS_SUCCESS,
        )
        .order_by('id')
        .first()
    )


def start_stk_payment(
    *,
    phone,
    amount,
    account_reference,
    description='',
    customer=None,
    initiated_by=None,
    invoice=None,
    subscription=None,
):
    """Create a pending MpesaPayment and fire STK Push. Returns the payment."""
    normalized = normalize_kenya_phone(phone)
    if not normalized:
        raise MpesaError(f'Invalid Kenyan mobile number: {phone!r}')

    payment = MpesaPayment.objects.create(
        source=MpesaPayment.SOURCE_STK,
        customer=customer,
        phone=normalized,
        amount=Decimal(str(amount)),
        account_reference=(account_reference or 'METROLINKS')[:64],
        description=(description or '')[:120],
        initiated_by=initiated_by,
        invoice=invoice,
        subscription=subscription,
        status=MpesaPayment.STATUS_PENDING,
    )

    try:
        result = initiate_stk_push(
            phone=normalized,
            amount=amount,
            account_reference=payment.account_reference,
            description=payment.description or payment.payment_id,
        )
    except MpesaError as exc:
        payment.status = MpesaPayment.STATUS_FAILED
        payment.result_desc = str(exc)[:255]
        payment.completed_at = timezone.now()
        payment.save(update_fields=[
            'status', 'result_desc', 'completed_at', 'updated_at',
        ])
        raise

    data = result['response']
    payment.merchant_request_id = data.get('MerchantRequestID') or ''
    payment.checkout_request_id = data.get('CheckoutRequestID') or ''
    payment.raw_stk_response = data
    payment.result_desc = data.get('CustomerMessage') or data.get('ResponseDescription') or ''
    payment.save(update_fields=[
        'merchant_request_id', 'checkout_request_id', 'raw_stk_response',
        'result_desc', 'updated_at',
    ])
    return payment


@transaction.atomic
def apply_stk_callback(body):
    """
    Idempotently update payment from Daraja callback.
    On success, extends / activates the customer subscription.
    Returns (payment, created_or_updated) or (None, False) if unmatched.
    """
    parsed = parse_stk_callback(body)
    checkout_id = parsed['checkout_request_id']
    merchant_id = parsed['merchant_request_id']

    payment = None
    if checkout_id:
        payment = (
            MpesaPayment.objects.select_for_update()
            .filter(checkout_request_id=checkout_id)
            .first()
        )
    if not payment and merchant_id:
        payment = (
            MpesaPayment.objects.select_for_update()
            .filter(merchant_request_id=merchant_id)
            .first()
        )

    if not payment:
        logger.warning(
            'STK callback for unknown payment checkout=%s merchant=%s',
            checkout_id, merchant_id,
        )
        return None, False

    # Already finalized — keep first successful outcome, still store latest raw
    if payment.is_terminal and payment.status == MpesaPayment.STATUS_SUCCESS:
        payment.raw_callback = parsed['raw']
        payment.save(update_fields=['raw_callback', 'updated_at'])
        if not payment.billing_applied_at:
            apply_successful_payment_to_subscription(payment)
        return payment, False

    result_code = parsed['result_code']
    payment.raw_callback = parsed['raw']
    payment.result_code = int(result_code) if result_code is not None else None
    payment.result_desc = (parsed['result_desc'] or '')[:255]

    if result_code in (0, '0'):
        payment.status = MpesaPayment.STATUS_SUCCESS
        if parsed['mpesa_receipt_number']:
            payment.mpesa_receipt_number = parsed['mpesa_receipt_number']
        if parsed['phone']:
            payment.phone = parsed['phone']
        if parsed['amount'] is not None:
            try:
                payment.amount = Decimal(str(parsed['amount']))
            except Exception:
                pass
    elif result_code in (1032, '1032'):
        payment.status = MpesaPayment.STATUS_CANCELLED
    else:
        payment.status = MpesaPayment.STATUS_FAILED

    payment.completed_at = timezone.now()
    payment.save()
    logger.info(
        'STK callback applied %s status=%s receipt=%s',
        payment.payment_id, payment.status, payment.mpesa_receipt_number,
    )

    if payment.status == MpesaPayment.STATUS_SUCCESS:
        try:
            apply_successful_payment_to_subscription(payment)
        except Exception:
            logger.exception(
                'Failed to apply STK %s to subscription', payment.payment_id,
            )

    return payment, True


def _resolve_payment_customer(payment):
    from core.models import MyUser

    if payment.customer_id:
        return payment.customer
    customer = MyUser.objects.filter(role='Customer', phone=payment.phone).first()
    if customer:
        payment.customer = customer
        payment.save(update_fields=['customer', 'updated_at'])
    return customer


def apply_successful_payment_to_subscription(payment):
    """
    On successful M-Pesa payment:
    - Resolve customer + subscription (or start one if amount matches a plan)
    - Mark open invoice paid / create paid invoice for the new period
    - Set expires_at = period_start + 1 calendar month (exact second)
    Idempotent via payment.billing_applied_at.
    """
    from billing.models import Invoice, Plan, Subscription
    from billing.period import add_one_billing_month

    payment = (
        MpesaPayment.objects.select_for_update()
        .select_related('customer', 'invoice', 'subscription', 'subscription__plan')
        .get(pk=payment.pk)
    )

    if payment.status != MpesaPayment.STATUS_SUCCESS:
        return None
    if payment.billing_applied_at:
        return payment.subscription

    paid_at = payment.completed_at or timezone.now()
    customer = _resolve_payment_customer(payment)

    sub = payment.subscription
    if sub is None and payment.invoice_id:
        sub = payment.invoice.subscription

    if sub is None and customer:
        sub = (
            Subscription.objects.filter(
                customer=customer, status=Subscription.STATUS_ACTIVE,
            )
            .select_related('plan')
            .first()
        )
        if sub is None:
            sub = (
                Subscription.objects.filter(customer=customer)
                .exclude(status=Subscription.STATUS_CANCELLED)
                .select_related('plan')
                .order_by('-expires_at')
                .first()
            )

    # No subscription yet — start one if amount matches a plan price
    if sub is None:
        if not customer:
            logger.info(
                'STK %s success but no customer/subscription to update',
                payment.payment_id,
            )
            return None
        plan = (
            Plan.objects.filter(is_active=True, price=payment.amount)
            .order_by('speed_mbps')
            .first()
        )
        if not plan:
            logger.info(
                'STK %s success KES %s — no matching plan/subscription',
                payment.payment_id, payment.amount,
            )
            return None
        sub, invoice = start_subscription(
            customer=customer, plan=plan, started_at=paid_at,
        )
        invoice.amount_paid = invoice.amount_due
        invoice.status = Invoice.STATUS_PAID
        invoice.save(update_fields=['amount_paid', 'status', 'updated_at'])
        payment.subscription = sub
        payment.invoice = invoice
        payment.billing_applied_at = timezone.now()
        payment.save(update_fields=[
            'subscription', 'invoice', 'billing_applied_at', 'updated_at',
        ])
        logger.info(
            'STK %s started subscription %s until %s',
            payment.payment_id, sub.pk, sub.expires_at,
        )
        _notify_payment_sms(payment, sub)
        _queue_network_after_payment(sub)
        return sub

    # Continuity: still active → stack from expires_at; else start from paid_at
    if (
        sub.status == Subscription.STATUS_ACTIVE
        and sub.expires_at
        and paid_at <= sub.expires_at
    ):
        period_start = sub.expires_at
    else:
        period_start = paid_at
    period_end = add_one_billing_month(period_start)

    invoice = payment.invoice
    if invoice and invoice.status in (
        Invoice.STATUS_ISSUED, Invoice.STATUS_PARTIAL, Invoice.STATUS_OVERDUE,
    ):
        pass
    else:
        invoice = (
            Invoice.objects.filter(
                subscription=sub,
                status__in=[
                    Invoice.STATUS_ISSUED,
                    Invoice.STATUS_PARTIAL,
                    Invoice.STATUS_OVERDUE,
                ],
            )
            .order_by('due_at', 'id')
            .first()
        )

    if invoice:
        invoice.amount_paid = invoice.amount_due
        invoice.status = Invoice.STATUS_PAID
        invoice.period_start = period_start
        invoice.period_end = period_end
        invoice.due_at = period_end
        invoice.save(update_fields=[
            'amount_paid', 'status', 'period_start', 'period_end', 'due_at', 'updated_at',
        ])
    else:
        invoice = Invoice.objects.create(
            subscription=sub,
            period_start=period_start,
            period_end=period_end,
            amount_due=sub.plan.price,
            amount_paid=min(payment.amount, sub.plan.price),
            status=Invoice.STATUS_PAID,
            due_at=period_end,
        )

    sub.started_at = period_start
    sub.expires_at = period_end
    sub.status = Subscription.STATUS_ACTIVE
    sub.save(update_fields=['started_at', 'expires_at', 'status', 'updated_at'])

    payment.subscription = sub
    payment.invoice = invoice
    payment.billing_applied_at = timezone.now()
    update_fields = ['subscription', 'invoice', 'billing_applied_at', 'updated_at']
    if customer and not payment.customer_id:
        payment.customer = customer
        update_fields.append('customer')
    payment.save(update_fields=update_fields)

    logger.info(
        'STK %s extended subscription %s → expires %s',
        payment.payment_id, sub.pk, sub.expires_at,
    )
    _notify_payment_sms(payment, sub)
    _queue_network_after_payment(sub)
    return sub


def _notify_payment_sms(payment, subscription):
    try:
        from billing.notifications import notify_payment_received
        notify_payment_received(payment, subscription)
    except Exception:
        logger.exception('Payment SMS hook failed for %s', payment.payment_id)


def _queue_network_after_payment(subscription):
    """Restore PPPoE + schedule disconnect — never block payment callback."""
    if not subscription:
        return
    try:
        from billing.tasks import restore_subscription_network
        restore_subscription_network.delay(subscription.pk)
    except Exception:
        logger.exception(
            'Failed to queue network restore for subscription %s',
            subscription.pk,
        )


def start_pull_transaction(
    *,
    mpesa_receipt,
    amount=None,
    phone='',
    customer=None,
    initiated_by=None,
    invoice=None,
    subscription=None,
    notes='',
):
    """
    Verify an off-app M-Pesa payment by receipt via Daraja Transaction Status.
    Creates a pending payment; ResultURL callback finalizes + renews subscription.
    """
    receipt = (mpesa_receipt or '').strip().upper()
    if not receipt:
        raise MpesaError('M-Pesa receipt number is required')

    existing = _existing_success_by_receipt(receipt)
    if existing:
        raise MpesaError(
            f'Receipt {receipt} is already recorded as {existing.payment_id}.'
        )

    pending = (
        MpesaPayment.objects.filter(
            mpesa_receipt_number__iexact=receipt,
            source=MpesaPayment.SOURCE_PULL,
            status=MpesaPayment.STATUS_PENDING,
        )
        .order_by('-id')
        .first()
    )
    if pending:
        raise MpesaError(
            f'Pull already in progress for {receipt} ({pending.payment_id}). '
            'Wait for Safaricom result or use Manual record if pull is down.'
        )

    normalized = normalize_kenya_phone(phone) if phone else ''
    if customer and not normalized:
        normalized = normalize_kenya_phone(customer.phone or '') or ''
    if not normalized:
        # Placeholder until ResultURL returns DebitPartyName
        normalized = '254700000000'

    payment = MpesaPayment.objects.create(
        source=MpesaPayment.SOURCE_PULL,
        customer=customer,
        phone=normalized,
        amount=Decimal(str(amount if amount is not None else 0)),
        account_reference=receipt[:64],
        description=(notes or f'Pull {receipt}')[:120],
        mpesa_receipt_number=receipt,
        initiated_by=initiated_by,
        invoice=invoice,
        subscription=subscription,
        status=MpesaPayment.STATUS_PENDING,
    )

    try:
        data = query_transaction_status(receipt, remarks=payment.payment_id)
    except MpesaError as exc:
        payment.status = MpesaPayment.STATUS_FAILED
        payment.result_desc = str(exc)[:255]
        payment.completed_at = timezone.now()
        payment.save(update_fields=[
            'status', 'result_desc', 'completed_at', 'updated_at',
        ])
        raise

    payment.originator_conversation_id = data.get('OriginatorConversationID') or ''
    payment.merchant_request_id = data.get('ConversationID') or ''
    payment.raw_stk_response = data
    payment.result_desc = data.get('ResponseDescription') or 'Query accepted'
    payment.save(update_fields=[
        'originator_conversation_id', 'merchant_request_id',
        'raw_stk_response', 'result_desc', 'updated_at',
    ])
    return payment


@transaction.atomic
def apply_transaction_status_result(body):
    """
    Apply Daraja Transaction Status ResultURL payload to a pull payment.
    Returns (payment, updated).
    """
    parsed = parse_transaction_status_result(body)
    originator = parsed['originator_conversation_id']
    receipt = parsed['mpesa_receipt_number'] or parsed['transaction_id']

    payment = None
    if originator:
        payment = (
            MpesaPayment.objects.select_for_update()
            .filter(originator_conversation_id=originator)
            .first()
        )
    if not payment and receipt:
        payment = (
            MpesaPayment.objects.select_for_update()
            .filter(
                mpesa_receipt_number__iexact=receipt,
                source=MpesaPayment.SOURCE_PULL,
            )
            .order_by('-id')
            .first()
        )

    if not payment:
        logger.warning(
            'Transaction status result unmatched originator=%s receipt=%s',
            originator, receipt,
        )
        return None, False

    payment.raw_callback = parsed['raw']
    result_code = parsed['result_code']
    try:
        result_code_int = int(result_code) if result_code is not None else None
    except (TypeError, ValueError):
        result_code_int = None

    if payment.is_terminal and payment.status == MpesaPayment.STATUS_SUCCESS:
        payment.save(update_fields=['raw_callback', 'updated_at'])
        if not payment.billing_applied_at:
            apply_successful_payment_to_subscription(payment)
        return payment, False

    payment.result_code = result_code_int
    payment.result_desc = (parsed['result_desc'] or '')[:255]
    if receipt:
        payment.mpesa_receipt_number = receipt[:64]
    if parsed['phone'] and payment.phone in ('', '254700000000'):
        payment.phone = parsed['phone']
    elif parsed['phone']:
        payment.phone = parsed['phone']

    ok = result_code_int == 0
    status_text = (parsed.get('transaction_status') or '').lower()
    if ok and status_text and status_text not in (
        'completed', 'success', 'successful', 'ok', '',
    ):
        # Some payloads still ResultCode 0 with Completed
        if 'fail' in status_text or 'cancel' in status_text:
            ok = False

    if ok:
        if parsed['amount'] is not None:
            try:
                payment.amount = Decimal(str(parsed['amount']))
            except Exception:
                pass
        payment.status = MpesaPayment.STATUS_SUCCESS
        payment.completed_at = timezone.now()
        if not payment.customer_id and payment.phone:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            payment.customer = (
                User.objects.filter(role='Customer', phone=payment.phone).first()
            )
    else:
        payment.status = MpesaPayment.STATUS_FAILED
        payment.completed_at = timezone.now()

    payment.save()
    if payment.status == MpesaPayment.STATUS_SUCCESS:
        apply_successful_payment_to_subscription(payment)
    return payment, True


@transaction.atomic
def record_manual_payment(
    *,
    amount,
    phone,
    customer=None,
    mpesa_receipt='',
    is_cash=False,
    notes='',
    initiated_by=None,
    invoice=None,
    subscription=None,
):
    """
    Staff records cash or an M-Pesa code when pull/STK is unavailable.
    Immediately marks success and applies subscription renewal.
    """
    normalized = normalize_kenya_phone(phone)
    if not normalized:
        raise MpesaError(f'Invalid Kenyan mobile number: {phone!r}')

    receipt = (mpesa_receipt or '').strip().upper()
    if is_cash:
        if not receipt:
            receipt = f'CASH-{uuid_hex()}'
    else:
        if not receipt:
            raise MpesaError('M-Pesa receipt / transaction code is required')
        existing = _existing_success_by_receipt(receipt)
        if existing:
            raise MpesaError(
                f'Receipt {receipt} is already recorded as {existing.payment_id}.'
            )

    if not customer:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        customer = User.objects.filter(role='Customer', phone=normalized).first()

    payment = MpesaPayment.objects.create(
        source=MpesaPayment.SOURCE_MANUAL,
        customer=customer,
        phone=normalized,
        amount=Decimal(str(amount)),
        account_reference=(receipt or 'MANUAL')[:64],
        description=(notes or ('Cash payment' if is_cash else 'Manual M-Pesa'))[:120],
        mpesa_receipt_number=receipt[:64],
        initiated_by=initiated_by,
        invoice=invoice,
        subscription=subscription,
        status=MpesaPayment.STATUS_SUCCESS,
        result_code=0,
        result_desc='Recorded manually by staff',
        completed_at=timezone.now(),
        raw_callback={'manual': True, 'is_cash': is_cash, 'notes': notes},
    )
    apply_successful_payment_to_subscription(payment)
    payment.refresh_from_db()
    return payment


def uuid_hex():
    import uuid
    return uuid.uuid4().hex[:10].upper()


def start_subscription(*, customer, plan, started_at=None, created_by=None):
    """Create the sole active subscription + first issued invoice for the period."""
    from django.core.exceptions import ValidationError

    from billing.models import Invoice, Subscription
    from billing.period import add_one_billing_month

    if customer.role != 'Customer':
        raise ValidationError('Subscriptions are only for customers.')
    if not plan.is_active:
        raise ValidationError('Selected plan is not active.')

    started = started_at or timezone.now()
    expires = add_one_billing_month(started)

    with transaction.atomic():
        if Subscription.objects.filter(customer=customer, status=Subscription.STATUS_ACTIVE).exists():
            raise ValidationError('Customer already has an active subscription.')

        sub = Subscription.objects.create(
            customer=customer,
            plan=plan,
            status=Subscription.STATUS_ACTIVE,
            started_at=started,
            expires_at=expires,
        )
        invoice = Invoice.objects.create(
            subscription=sub,
            period_start=started,
            period_end=expires,
            amount_due=plan.price,
            amount_paid=0,
            status=Invoice.STATUS_ISSUED,
            due_at=expires,
        )
    _queue_network_after_payment(sub)
    return sub, invoice


def renew_subscription(subscription, paid_at=None, mark_paid=False):
    """Extend subscription by one billing month from continuity or payment time."""
    from billing.models import Invoice, Subscription
    from billing.period import add_one_billing_month

    paid = paid_at or timezone.now()
    if subscription.expires_at and paid <= subscription.expires_at:
        period_start = subscription.expires_at
    else:
        period_start = paid
    period_end = add_one_billing_month(period_start)

    with transaction.atomic():
        subscription.started_at = period_start
        subscription.expires_at = period_end
        subscription.status = Subscription.STATUS_ACTIVE
        subscription.save(update_fields=['started_at', 'expires_at', 'status', 'updated_at'])
        invoice = Invoice.objects.create(
            subscription=subscription,
            period_start=period_start,
            period_end=period_end,
            amount_due=subscription.plan.price,
            amount_paid=subscription.plan.price if mark_paid else 0,
            status=Invoice.STATUS_PAID if mark_paid else Invoice.STATUS_ISSUED,
            due_at=period_end,
        )
    return subscription, invoice


def mark_expired_subscriptions(now=None):
    """Flip active subscriptions past expires_at to expired; mark open invoices overdue."""
    from billing.models import Invoice, Subscription

    now = now or timezone.now()
    expired_ids = list(
        Subscription.objects.filter(
            status=Subscription.STATUS_ACTIVE,
            expires_at__lte=now,
        ).values_list('id', flat=True)
    )
    n_sub = Subscription.objects.filter(id__in=expired_ids).update(
        status=Subscription.STATUS_EXPIRED,
        updated_at=now,
    )
    n_inv = Invoice.objects.filter(
        subscription_id__in=expired_ids,
        status__in=[Invoice.STATUS_ISSUED, Invoice.STATUS_PARTIAL],
        due_at__lte=now,
    ).update(status=Invoice.STATUS_OVERDUE, updated_at=now)

    # Best-effort suspend (Celery ETA is primary; this catches missed jobs)
    if expired_ids:
        try:
            from billing.network_services import on_subscription_expired
            for sub in Subscription.objects.filter(id__in=expired_ids).select_related('customer', 'plan'):
                on_subscription_expired(sub, reason='expire')
        except Exception:
            logger.exception('Network suspend after mark_expired failed')

    return n_sub, n_inv
