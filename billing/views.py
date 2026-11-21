"""Staff M-Pesa STK UI and Safaricom callback."""
import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from billing.forms import ExpenditureForm, ManualPaymentForm, PullTransactionForm, StkPushForm
from billing.models import Expenditure, MpesaPayment
from billing.mpesa import MpesaError, mpesa_configured, transaction_status_configured
from billing.services import (
    apply_stk_callback,
    apply_transaction_status_result,
    record_manual_payment,
    start_pull_transaction,
    start_stk_payment,
)
logger = logging.getLogger(__name__)


def _require_billing_staff(user):
    if not user.is_authenticated or user.role not in ('Admin', 'Receptionist'):
        raise PermissionDenied


@login_required(login_url='/login/')
def expenditure_list_view(request):
    _require_billing_staff(request.user)
    q = (request.GET.get('q') or '').strip()
    method = (request.GET.get('method') or '').strip()

    qs = Expenditure.objects.all()
    if method:
        qs = qs.filter(payment_method=method)
    if q:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
        )

    page = Paginator(qs, 50).get_page(request.GET.get('page'))
    from django.db.models import Sum
    total = qs.aggregate(s=Sum('amount'))['s'] or 0

    return render(request, 'billing/expenditure_list.html', {
        'page_obj': page,
        'expenditures': page,
        'q': q,
        'method': method,
        'method_choices': Expenditure.METHOD_CHOICES,
        'total_amount': total,
    })


@login_required(login_url='/login/')
def expenditure_create_view(request):
    _require_billing_staff(request.user)

    if request.method == 'POST':
        form = ExpenditureForm(request.POST)
        if form.is_valid():
            expense = form.save()
            messages.success(
                request,
                f'Expense recorded: {expense.title} — KES {expense.amount}.',
            )
            return redirect('billing_expenditure_list')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = ExpenditureForm()

    return render(request, 'billing/expenditure_form.html', {
        'form': form,
        'page_title': 'Add expense',
    })


@login_required(login_url='/login/')
def payment_list_view(request):
    _require_billing_staff(request.user)
    q = (request.GET.get('q') or '').strip()
    status = (request.GET.get('status') or '').strip()

    qs = MpesaPayment.objects.select_related('customer', 'initiated_by').all()
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(
            Q(payment_id__icontains=q)
            | Q(phone__icontains=q)
            | Q(mpesa_receipt_number__icontains=q)
            | Q(account_reference__icontains=q)
            | Q(checkout_request_id__icontains=q)
        )

    page = Paginator(qs, 50).get_page(request.GET.get('page'))
    return render(request, 'billing/payment_list.html', {
        'page_obj': page,
        'payments': page,
        'q': q,
        'status': status,
        'status_choices': MpesaPayment.STATUS_CHOICES,
        'mpesa_ready': mpesa_configured(),
    })


@login_required(login_url='/login/')
def payment_detail_view(request, payment_id):
    _require_billing_staff(request.user)
    payment = get_object_or_404(
        MpesaPayment.objects.select_related('customer', 'initiated_by'),
        payment_id=payment_id,
    )
    return render(request, 'billing/payment_detail.html', {
        'payment': payment,
        'mpesa_ready': mpesa_configured(),
    })


@login_required(login_url='/login/')
def stk_push_view(request):
    _require_billing_staff(request.user)

    initial = {}
    customer = None
    customer_id = request.GET.get('customer')
    if customer_id:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        customer = User.objects.filter(pk=customer_id, role='Customer').first()
        if customer:
            initial['customer'] = customer.pk
            initial['phone'] = customer.phone
            initial['account_reference'] = (customer.phone or 'METROLINKS')[-9:]
            try:
                from billing.models import Subscription
                sub = (
                    Subscription.objects.filter(customer=customer, status='active')
                    .select_related('plan')
                    .first()
                )
                if sub:
                    initial['amount'] = sub.plan.price
                    initial['description'] = f'{sub.plan.speed_mbps}Mbps'
            except Exception:
                pass

    invoice = None
    invoice_id = request.GET.get('invoice')
    if invoice_id:
        from billing.models import Invoice
        invoice = (
            Invoice.objects.select_related('subscription__customer', 'subscription__plan')
            .filter(invoice_id=invoice_id)
            .first()
        )
        if invoice:
            initial['amount'] = invoice.amount_due - invoice.amount_paid
            initial['description'] = 'Invoice'
            initial['account_reference'] = invoice.invoice_id.replace('INV-', '')[:12]
            if invoice.subscription.customer_id:
                initial['customer'] = invoice.subscription.customer_id
                initial['phone'] = invoice.subscription.customer.phone

    if request.method == 'POST':
        form = StkPushForm(request.POST)
        if form.is_valid():
            if not mpesa_configured():
                messages.error(
                    request,
                    'M-Pesa is not configured. Add Daraja credentials to .env first.',
                )
            else:
                try:
                    linked_invoice = None
                    linked_sub = None
                    if invoice_id:
                        from billing.models import Invoice
                        linked_invoice = Invoice.objects.filter(invoice_id=invoice_id).first()
                        if linked_invoice:
                            linked_sub = linked_invoice.subscription
                    elif form.cleaned_data.get('customer'):
                        from billing.models import Subscription
                        linked_sub = (
                            Subscription.objects.filter(
                                customer=form.cleaned_data['customer'],
                                status='active',
                            ).first()
                        )
                    payment = start_stk_payment(
                        phone=form.cleaned_data['phone'],
                        amount=form.cleaned_data['amount'],
                        account_reference=(
                            form.cleaned_data.get('account_reference')
                            or form.cleaned_data['phone'][-9:]
                        ),
                        description=form.cleaned_data.get('description') or 'Payment',
                        customer=form.cleaned_data.get('customer'),
                        initiated_by=request.user,
                        invoice=linked_invoice,
                        subscription=linked_sub,
                    )
                    messages.success(
                        request,
                        f'STK Push sent to {payment.phone}. '
                        f'Ask the customer to enter their M-Pesa PIN. '
                        f'Ref: {payment.payment_id}',
                    )
                    return redirect('billing_payment_detail', payment_id=payment.payment_id)
                except MpesaError as exc:
                    messages.error(request, str(exc))
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = StkPushForm(initial=initial)

    return render(request, 'billing/stk_push.html', {
        'form': form,
        'mpesa_ready': mpesa_configured(),
        'prefill_customer': customer,
    })


@csrf_exempt
@require_POST
def mpesa_stk_callback(request):
    """Safaricom Daraja STK callback — must be publicly reachable over HTTPS."""
    try:
        body = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        logger.warning('M-Pesa callback: invalid JSON')
        return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Invalid JSON'}, status=400)

    logger.info('M-Pesa STK callback received: %s', json.dumps(body)[:500])
    try:
        payment, updated = apply_stk_callback(body)
    except Exception:
        logger.exception('M-Pesa callback processing failed')
        # Still acknowledge so Daraja does not retry forever aggressively
        return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})

    if payment:
        logger.info(
            'Callback for %s updated=%s status=%s',
            payment.payment_id, updated, payment.status,
        )
    return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})


def _payment_form_initial(request):
    """Shared ?customer= / ?invoice= prefills for pull + manual forms."""
    from django.contrib.auth import get_user_model

    from billing.models import Invoice, Subscription

    initial = {}
    customer = None
    customer_id = request.GET.get('customer')
    if customer_id:
        User = get_user_model()
        customer = User.objects.filter(pk=customer_id, role='Customer').first()
        if customer:
            initial['customer'] = customer.pk
            initial['phone'] = customer.phone
            sub = (
                Subscription.objects.filter(customer=customer, status='active')
                .select_related('plan')
                .first()
            )
            if sub:
                initial['amount'] = sub.plan.price

    invoice = None
    invoice_id = request.GET.get('invoice')
    if invoice_id:
        invoice = (
            Invoice.objects.select_related('subscription__customer', 'subscription__plan')
            .filter(invoice_id=invoice_id)
            .first()
        )
        if invoice:
            initial['amount'] = invoice.amount_due - invoice.amount_paid
            if invoice.subscription.customer_id:
                initial['customer'] = invoice.subscription.customer_id
                initial['phone'] = invoice.subscription.customer.phone
    return initial, customer, invoice


@login_required(login_url='/login/')
def pull_transaction_view(request):
    """Ask Safaricom to confirm an off-app M-Pesa receipt (paybill/till)."""
    from billing.models import Subscription

    _require_billing_staff(request.user)
    initial, customer, invoice = _payment_form_initial(request)

    if request.method == 'POST':
        form = PullTransactionForm(request.POST)
        if form.is_valid():
            if not transaction_status_configured():
                messages.error(
                    request,
                    'Pull transaction is not configured (initiator / security credential). '
                    'Use Manual record instead, or add MPESA_INITIATOR_NAME and '
                    'MPESA_SECURITY_CREDENTIAL to .env.',
                )
            else:
                try:
                    linked_invoice = invoice
                    linked_sub = linked_invoice.subscription if linked_invoice else None
                    if linked_sub is None and form.cleaned_data.get('customer'):
                        linked_sub = (
                            Subscription.objects.filter(
                                customer=form.cleaned_data['customer'],
                                status='active',
                            ).first()
                        )
                    payment = start_pull_transaction(
                        mpesa_receipt=form.cleaned_data['mpesa_receipt'],
                        amount=form.cleaned_data.get('amount'),
                        phone=form.cleaned_data.get('phone') or '',
                        customer=form.cleaned_data.get('customer'),
                        initiated_by=request.user,
                        invoice=linked_invoice,
                        subscription=linked_sub,
                        notes=form.cleaned_data.get('notes') or '',
                    )
                    messages.success(
                        request,
                        f'Pull started for receipt {payment.mpesa_receipt_number}. '
                        f'Waiting for Safaricom confirmation ({payment.payment_id}).',
                    )
                    return redirect('billing_payment_detail', payment_id=payment.payment_id)
                except MpesaError as exc:
                    messages.error(request, str(exc))
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = PullTransactionForm(initial=initial)

    return render(request, 'billing/pull_transaction.html', {
        'form': form,
        'pull_ready': transaction_status_configured(),
        'prefill_customer': customer,
    })


@login_required(login_url='/login/')
def manual_payment_view(request):
    """Fallback: staff types cash or M-Pesa code when pull/STK is down."""
    from billing.models import Subscription

    _require_billing_staff(request.user)
    initial, customer, invoice = _payment_form_initial(request)

    if request.method == 'POST':
        form = ManualPaymentForm(request.POST)
        if form.is_valid():
            try:
                linked_invoice = invoice
                linked_sub = linked_invoice.subscription if linked_invoice else None
                cust = form.cleaned_data.get('customer')
                if linked_sub is None and cust:
                    linked_sub = (
                        Subscription.objects.filter(
                            customer=cust, status='active',
                        ).first()
                    )
                payment = record_manual_payment(
                    amount=form.cleaned_data['amount'],
                    phone=form.cleaned_data['phone'],
                    customer=cust,
                    mpesa_receipt=form.cleaned_data.get('mpesa_receipt') or '',
                    is_cash=form.cleaned_data['method'] == ManualPaymentForm.METHOD_CASH,
                    notes=form.cleaned_data.get('notes') or '',
                    initiated_by=request.user,
                    invoice=linked_invoice,
                    subscription=linked_sub,
                )
                messages.success(
                    request,
                    f'Payment recorded ({payment.payment_id}). '
                    f'Receipt {payment.mpesa_receipt_number} — KES {payment.amount}.',
                )
                return redirect('billing_payment_detail', payment_id=payment.payment_id)
            except MpesaError as exc:
                messages.error(request, str(exc))
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ManualPaymentForm(initial=initial)

    return render(request, 'billing/manual_payment.html', {
        'form': form,
        'prefill_customer': customer,
        'pull_ready': transaction_status_configured(),
    })


@csrf_exempt
@require_POST
def mpesa_transaction_result(request):
    """Safaricom Transaction Status ResultURL callback."""
    try:
        body = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        logger.warning('M-Pesa transaction result: invalid JSON')
        return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Invalid JSON'}, status=400)

    logger.info('M-Pesa transaction status result: %s', json.dumps(body)[:800])
    try:
        payment, updated = apply_transaction_status_result(body)
    except Exception:
        logger.exception('Transaction status result processing failed')
        return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})

    if payment:
        logger.info(
            'Pull result for %s updated=%s status=%s',
            payment.payment_id, updated, payment.status,
        )
    return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})


@csrf_exempt
@require_POST
def mpesa_transaction_timeout(request):
    """Safaricom QueueTimeoutURL for transaction status — mark pull failed."""
    try:
        body = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        body = {}
    logger.warning('M-Pesa transaction status timeout: %s', json.dumps(body)[:500])
    result = body.get('Result') or body
    originator = result.get('OriginatorConversationID') or ''
    if originator:
        payment = MpesaPayment.objects.filter(
            originator_conversation_id=originator,
            status=MpesaPayment.STATUS_PENDING,
            source=MpesaPayment.SOURCE_PULL,
        ).first()
        if payment:
            from django.utils import timezone
            payment.status = MpesaPayment.STATUS_FAILED
            payment.result_desc = 'Transaction status query timed out'
            payment.raw_callback = body
            payment.completed_at = timezone.now()
            payment.save(update_fields=[
                'status', 'result_desc', 'raw_callback', 'completed_at', 'updated_at',
            ])
    return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})


# --- Phase 1: Plans / Subscriptions / Invoices ---

from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from billing.forms import PlanForm, StartSubscriptionForm
from billing.models import Invoice, Plan, Subscription
from billing.services import start_subscription


@login_required(login_url='/login/')
def plan_list_view(request):
    _require_billing_staff(request.user)
    plans = Plan.objects.all()
    return render(request, 'billing/plan_list.html', {'plans': plans})


@login_required(login_url='/login/')
def plan_create_view(request):
    _require_billing_staff(request.user)
    if request.method == 'POST':
        form = PlanForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Plan created.')
            return redirect('billing_plan_list')
    else:
        form = PlanForm()
    return render(request, 'billing/plan_form.html', {'form': form, 'title': 'Create plan'})


@login_required(login_url='/login/')
def plan_edit_view(request, pk):
    _require_billing_staff(request.user)
    plan = get_object_or_404(Plan, pk=pk)
    if request.method == 'POST':
        form = PlanForm(request.POST, instance=plan)
        if form.is_valid():
            form.save()
            messages.success(request, 'Plan updated.')
            return redirect('billing_plan_list')
    else:
        form = PlanForm(instance=plan)
    return render(request, 'billing/plan_form.html', {'form': form, 'title': 'Edit plan', 'plan': plan})


@login_required(login_url='/login/')
def invoice_list_view(request):
    _require_billing_staff(request.user)
    status = (request.GET.get('status') or '').strip()
    q = (request.GET.get('q') or '').strip()
    qs = Invoice.objects.select_related(
        'subscription__customer', 'subscription__plan'
    ).all()
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(
            Q(invoice_id__icontains=q)
            | Q(subscription__customer__email__icontains=q)
            | Q(subscription__customer__phone__icontains=q)
            | Q(subscription__customer__first_name__icontains=q)
            | Q(subscription__customer__last_name__icontains=q)
        )
    page = Paginator(qs, 50).get_page(request.GET.get('page'))
    return render(request, 'billing/invoice_list.html', {
        'page_obj': page,
        'invoices': page,
        'status': status,
        'q': q,
        'status_choices': Invoice.STATUS_CHOICES,
    })


@login_required(login_url='/login/')
def invoice_detail_view(request, invoice_id):
    _require_billing_staff(request.user)
    invoice = get_object_or_404(
        Invoice.objects.select_related('subscription__customer', 'subscription__plan'),
        invoice_id=invoice_id,
    )
    return render(request, 'billing/invoice_detail.html', {'invoice': invoice})


@login_required(login_url='/login/')
def customer_subscribe_view(request, customer_id):
    _require_billing_staff(request.user)
    User = get_user_model()
    customer = get_object_or_404(User, pk=customer_id, role='Customer')
    active = Subscription.objects.filter(
        customer=customer, status=Subscription.STATUS_ACTIVE
    ).select_related('plan').first()

    if request.method == 'POST':
        if active:
            messages.error(request, 'Customer already has an active subscription.')
            return redirect('customer_detail', pk=customer.pk)
        form = StartSubscriptionForm(request.POST)
        if form.is_valid():
            try:
                sub, invoice = start_subscription(
                    customer=customer,
                    plan=form.cleaned_data['plan'],
                    started_at=form.cleaned_data.get('started_at'),
                    created_by=request.user,
                )
            except ValidationError as e:
                msg = '; '.join(e.messages) if hasattr(e, 'messages') else str(e)
                messages.error(request, msg)
            else:
                messages.success(
                    request,
                    f'Subscribed to {sub.plan.name}. '
                    f'Expires {sub.expires_at:%Y-%m-%d %H:%M:%S}. '
                    f'Invoice {invoice.invoice_id}.',
                )
                return redirect('customer_detail', pk=customer.pk)
    else:
        form = StartSubscriptionForm()

    return render(request, 'billing/subscribe_form.html', {
        'form': form,
        'customer': customer,
        'active_subscription': active,
    })
