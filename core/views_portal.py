"""Customer portal — Django auth (MyUser role=Customer)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from core.customer_accounts import create_customer_user, find_customer_by_email_phone, find_customer_by_phone
from core.forms_portal import (
    CustomerPortalActivateForm,
    CustomerPortalLoginForm,
    CustomerPortalRegisterForm,
    CustomerPortalTicketLookupForm,
    CustomerTicketForm,
)
from core.models import Ticket, TicketComments, TicketAttachments, TicketAssignment
from core.portal_auth import (
    authenticate_customer,
    customer_portal_required,
    customer_owns_ticket,
    get_portal_customer,
    login_portal_user,
    logout_portal_customer,
    verify_ticket_access,
)


def portal_home(request):
    if request.user.is_authenticated and request.user.role == 'Customer':
        return redirect('portal_ticket_list')
    return redirect('portal_login')


def portal_login(request):
    if request.user.is_authenticated:
        if request.user.role == 'Customer':
            return redirect('portal_ticket_list')
        from core.views import redirect_after_login
        messages.info(request, 'You are signed in as staff — opening the agent dashboard.')
        return redirect_after_login(request.user)

    login_form = CustomerPortalLoginForm()
    register_form = CustomerPortalRegisterForm()
    activate_form = CustomerPortalActivateForm()
    lookup_form = CustomerPortalTicketLookupForm()
    mode = request.GET.get('mode', 'login')

    if request.method == 'POST':
        action = request.POST.get('action', 'login')

        if action == 'lookup':
            lookup_form = CustomerPortalTicketLookupForm(request.POST)
            mode = 'lookup'
            if lookup_form.is_valid():
                result = verify_ticket_access(
                    lookup_form.cleaned_data['ticket_id'],
                    lookup_form.cleaned_data['phone'],
                )
                if result:
                    ticket, customer_user = result
                    if customer_user.has_usable_password():
                        messages.info(
                            request,
                            'Please sign in with your phone number and password for full access.',
                        )
                        return redirect('portal_login')
                    login_portal_user(request, customer_user)
                    messages.success(request, 'Welcome — here is your ticket.')
                    return redirect('portal_ticket_detail', ticket_id=ticket.ticket_id)
                messages.error(request, 'Ticket ID and phone do not match our records.')

        elif action == 'register':
            register_form = CustomerPortalRegisterForm(request.POST)
            mode = 'register'
            if register_form.is_valid():
                try:
                    user = create_customer_user(
                        contact_name=register_form.cleaned_data['contact_name'],
                        phone=register_form.cleaned_data['phone'],
                        password=register_form.cleaned_data['password'],
                    )
                    login_portal_user(request, user)
                    messages.success(request, f'Account created. Welcome, {user.display_name}!')
                    return redirect('portal_ticket_list')
                except ValueError as exc:
                    messages.error(request, str(exc))

        elif action == 'activate':
            activate_form = CustomerPortalActivateForm(request.POST)
            mode = 'activate'
            if activate_form.is_valid():
                user = find_customer_by_phone(activate_form.cleaned_data['phone'])
                if user:
                    user.set_password(activate_form.cleaned_data['password'])
                    user.save(update_fields=['password'])
                    login_portal_user(request, user)
                    messages.success(request, 'Password set. You are now signed in.')
                    return redirect('portal_ticket_list')
                messages.error(request, 'No account found for that phone number.')

        else:
            login_form = CustomerPortalLoginForm(request.POST)
            mode = 'login'
            if login_form.is_valid():
                user, reason = authenticate_customer(
                    login_form.cleaned_data['phone'],
                    login_form.cleaned_data['password'],
                )
                if user:
                    login_portal_user(request, user)
                    messages.success(request, f'Welcome back, {user.display_name}!')
                    return redirect('portal_ticket_list')
                if reason == 'staff_account':
                    messages.info(
                        request,
                        'That is a staff account. Use agent login (phone or email + password).',
                    )
                    return redirect('login')
                elif reason == 'no_password':
                    messages.error(
                        request,
                        'No portal password set yet. Use the Activate tab to set one using your phone number.',
                    )
                else:
                    messages.error(
                        request,
                        'Invalid phone number or password. '
                        'If staff created your account, your default password is your phone number (e.g. 0712345678).',
                    )

    return render(request, 'core/portal/login.html', {
        'login_form': login_form,
        'register_form': register_form,
        'activate_form': activate_form,
        'lookup_form': lookup_form,
        'mode': mode,
    })


@require_POST
def portal_logout(request):
    logout_portal_customer(request)
    messages.info(request, 'You have been signed out of the customer portal.')
    return redirect('portal_login')


@login_required(login_url='/portal/login/')
@customer_portal_required
def portal_ticket_list(request):
    customer = get_portal_customer(request)
    status_filter = request.GET.get('status', '').strip()

    ACTIVE_STATUSES = ['Open', 'In Progress', 'On Hold']

    tickets = Ticket.objects.filter(customer=customer).prefetch_related(
        'categories',
    ).order_by('-created_at')

    if status_filter in ('Resolved', 'Closed'):
        tickets = tickets.filter(status=status_filter)
    elif status_filter and status_filter not in ('', 'active'):
        tickets = tickets.filter(status=status_filter)
    else:
        # Default: hide resolved/closed
        tickets = tickets.filter(status__in=ACTIVE_STATUSES)
        status_filter = 'active'

    return render(request, 'core/portal/ticket_list.html', {
        'customer': customer,
        'tickets': tickets,
        'status_filter': status_filter,
    })


@login_required(login_url='/portal/login/')
@customer_portal_required
def portal_ticket_create(request):
    customer = get_portal_customer(request)

    if request.method == 'POST':
        form = CustomerTicketForm(request.POST)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.customer = customer
            ticket.status = 'Open'
            ticket.save()
            form.save_m2m()
            from core.notifications import notify_ticket_created
            notify_ticket_created(ticket, source='portal_create')
            from core.ticket_urls import ticket_created_flash_message
            messages.success(
                request,
                ticket_created_flash_message(ticket, request, for_customer=True),
            )
            return redirect('portal_ticket_detail', ticket_id=ticket.ticket_id)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = CustomerTicketForm()

    return render(request, 'core/portal/ticket_create.html', {
        'customer': customer,
        'form': form,
    })


@login_required(login_url='/portal/login/')
@customer_portal_required
def portal_ticket_detail(request, ticket_id):
    customer = get_portal_customer(request)
    ticket = get_object_or_404(
        Ticket.objects.select_related('customer').prefetch_related('categories'),
        ticket_id=ticket_id,
    )

    if not customer_owns_ticket(customer, ticket):
        messages.error(request, 'You do not have access to this ticket.')
        return redirect('portal_ticket_list')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add_comment':
            comment_text = request.POST.get('comment', '').strip()
            if comment_text:
                TicketComments.objects.create(
                    ticket=ticket,
                    comment=comment_text,
                    commented_by=customer,
                )
                messages.success(request, 'Your message was added.')
            else:
                messages.error(request, 'Message cannot be empty.')
            return redirect('portal_ticket_detail', ticket_id=ticket.ticket_id)

        if action == 'add_attachment':
            attachment_file = request.FILES.get('attachment')
            if attachment_file:
                TicketAttachments.objects.create(ticket=ticket, attachment=attachment_file)
                messages.success(request, 'File uploaded successfully.')
            else:
                messages.error(request, 'Please select a file to upload.')
            return redirect('portal_ticket_detail', ticket_id=ticket.ticket_id)

    comments = TicketComments.objects.filter(ticket=ticket).select_related(
        'commented_by',
    ).order_by('commented_at')
    attachments = TicketAttachments.objects.filter(ticket=ticket).order_by('uploaded_at')
    assignment = TicketAssignment.objects.filter(ticket=ticket).select_related('assigned_to').first()

    return render(request, 'core/portal/ticket_detail.html', {
        'customer': customer,
        'ticket': ticket,
        'comments': comments,
        'attachments': attachments,
        'assignment': assignment,
    })
