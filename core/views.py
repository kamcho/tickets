from collections import defaultdict

from django.conf import settings
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Count, Prefetch
from django_hosts.resolvers import reverse as host_reverse
from .models import MyUser, Ticket, TicketCategory, TicketAssignment, TicketComments, TicketAttachments
from .ticket_urls import ticket_created_flash_message
from .forms import (
    TicketForm, CommentForm, AttachmentForm, UserCreateForm, CustomerForm,
    ProfileForm, ProfilePasswordForm,
)


def redirect_after_login(user):
    if user.role == 'Customer':
        return redirect('portal_ticket_list')
    if settings.DEBUG:
        return redirect('home')
    return redirect(host_reverse('home', host='tickets'))


def redirect_to_portal_home():
    """Send authenticated staff to the ticket dashboard."""
    if settings.DEBUG:
        return redirect('home')
    return redirect(host_reverse('home', host='tickets'))


def landing_page(request):
    # MyUser.objects.all().delete()
    if request.user.is_authenticated:
        if request.user.role == 'Customer':
            return redirect('portal_ticket_list')
        if settings.DEBUG:
            return redirect_to_portal_home()
    return render(request, "core/landing.html")


def login_view(request):
    if request.user.is_authenticated:
        return redirect_after_login(request.user)

    if request.method == "POST":
        login_id = (request.POST.get("username") or "").strip()
        password = request.POST.get("password")

        user = authenticate(
            request,
            username=login_id,
            password=password,
        )

        if user is not None:
            if user.role == 'Customer':
                messages.info(request, "Customer accounts use the Client Portal.")
                return redirect('portal_login')
            login(request, user)
            messages.success(request, f"Welcome back, {user.display_name}!")
            return redirect_after_login(user)
        else:
            messages.error(request, "Invalid phone, email, or password.")

    return render(request, "core/login.html")

@login_required(login_url='/login/')
def logout_view(request):
    if request.method == "POST":
        logout(request)
        messages.info(request, "You have been logged out successfully.")
    return redirect("/login/")


@login_required(login_url='/login/')
def profile_view(request):
    """View and update the signed-in user's profile."""
    if request.user.role == 'Customer':
        return redirect('portal_ticket_list')

    user = request.user
    profile_form = ProfileForm(instance=user)
    password_form = ProfilePasswordForm()

    if request.method == 'POST':
        action = request.POST.get('action', 'profile')

        if action == 'password':
            password_form = ProfilePasswordForm(request.POST)
            if password_form.is_valid():
                if not user.check_password(password_form.cleaned_data['current_password']):
                    messages.error(request, 'Current password is incorrect.')
                else:
                    user.set_password(password_form.cleaned_data['new_password'])
                    user.save(update_fields=['password'])
                    messages.success(request, 'Password updated successfully.')
                    return redirect('profile')
            messages.error(request, 'Please correct the password errors below.')
        else:
            profile_form = ProfileForm(request.POST, instance=user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, 'Profile updated successfully.')
                return redirect('profile')
            messages.error(request, 'Please correct the errors below.')

    return render(request, 'core/profile.html', {
        'profile_form': profile_form,
        'password_form': password_form,
        'user': user,
    })


@login_required(login_url='/login/')
def home_view(request):
    if request.user.role == 'Customer':
        return redirect('portal_ticket_list')
    is_agent = request.user.role == 'Field Agent'
    
    # Fetch filter params
    status_filter = request.GET.get('status', '')
    priority_filter = request.GET.get('priority', '')
    category_filter = request.GET.get('category', '')
    search_query = request.GET.get('search', '')

    ACTIVE_STATUSES = ['Open', 'In Progress', 'On Hold']
    RESOLVED_STATUSES = ['Resolved', 'Closed']

    tickets = Ticket.objects.prefetch_related(
        'categories',
        Prefetch(
            'ticketassignment_set',
            queryset=TicketAssignment.objects.select_related('assigned_to').order_by('-assigned_at'),
        ),
    ).order_by('-created_at')

    # If user is a Field Agent, scope to their assignments only
    if is_agent:
        tickets = tickets.filter(ticketassignment__assigned_to=request.user)

    # Default: hide Resolved/Closed unless the user explicitly filters for them
    if status_filter in ('', 'active'):
        tickets = tickets.filter(status__in=ACTIVE_STATUSES)
        status_filter = 'active'
    elif status_filter not in RESOLVED_STATUSES:
        # A specific non-resolved status was requested (e.g. Open, In Progress)
        tickets = tickets.filter(status=status_filter)
    else:
        # Resolved or Closed explicitly requested
        tickets = tickets.filter(status=status_filter)
    if priority_filter:
        tickets = tickets.filter(priority=priority_filter)
    if category_filter:
        tickets = tickets.filter(categories__id=category_filter).distinct()
    if search_query:
        tickets = tickets.filter(
            Q(ticket_id__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    # Compute metrics based on role context
    if is_agent:
        agent_tickets = Ticket.objects.filter(ticketassignment__assigned_to=request.user)
        total_count = agent_tickets.count()
        open_count = agent_tickets.filter(status='Open').count()
        pending_count = agent_tickets.filter(status__in=['In Progress', 'On Hold']).count()
        resolved_count = agent_tickets.filter(status__in=['Resolved', 'Closed']).count()
    else:
        total_count = Ticket.objects.count()
        open_count = Ticket.objects.filter(status='Open').count()
        pending_count = Ticket.objects.filter(status__in=['In Progress', 'On Hold']).count()
        resolved_count = Ticket.objects.filter(status__in=['Resolved', 'Closed']).count()

    categories = TicketCategory.objects.all()

    context = {
        'tickets': tickets,
        'categories': categories,
        'metrics': {
            'total': total_count,
            'open': open_count,
            'pending': pending_count,
            'resolved': resolved_count,
        },
        'filters': {
            'status': status_filter,
            'priority': priority_filter,
            'category': category_filter,
            'search': search_query,
        },
        'is_agent': is_agent
    }
    return render(request, "core/home.html", context)

def _save_ticket_with_attachment(request, ticket, form=None, sms_source='ticket_create_page'):
    from core.sms_debug import sms_debug

    sms_debug(sms_source, 'ticket_saved', ticket_id=ticket.ticket_id, customer_id=ticket.customer_id)
    ticket.save()
    if form is not None:
        form.save_m2m()
    attachment_file = request.FILES.get('attachment')
    if attachment_file:
        TicketAttachments.objects.create(
            ticket=ticket,
            attachment=attachment_file
        )
        sms_debug(sms_source, 'attachment_saved', ticket_id=ticket.ticket_id)
    from core.notifications import notify_ticket_created
    notify_ticket_created(ticket, source=sms_source)
    return ticket


def _user_can_create_tickets(user):
    return user.role in ('Admin', 'Receptionist')


def _user_can_assign_tickets(user):
    return user.role in ['Admin', 'Receptionist'] or user.is_staff


def _require_admin_or_receptionist(user):
    """Raise 403 if the user is not an Admin or Receptionist."""
    if user.role not in ('Admin', 'Receptionist'):
        raise PermissionDenied


def _require_admin(user):
    """Raise 403 if the user is not an Admin."""
    if user.role != 'Admin':
        raise PermissionDenied


def _apply_ticket_assignment(ticket, form, user, sms_source='ticket_create_page'):
    from core.sms_debug import sms_debug

    if not _user_can_assign_tickets(user):
        sms_debug(sms_source, 'assign_skip', reason='user_cannot_assign', user_role=user.role)
        return None
    assigned_to = form.cleaned_data.get('assigned_to')
    if not assigned_to:
        sms_debug(sms_source, 'assign_skip', reason='no_agent_in_form', ticket_id=ticket.ticket_id)
        return None
    sms_debug(
        sms_source,
        'assign_from_form',
        ticket_id=ticket.ticket_id,
        agent_id=assigned_to.pk,
        agent_email=assigned_to.email,
    )
    from core.notifications import assign_ticket_to_agent
    assign_ticket_to_agent(ticket, assigned_to, source=sms_source)
    return assigned_to


def _hybrid_search_slice(queryset, limit=None):
    """Return up to `limit` rows and whether more exist."""
    limit = limit or settings.HYBRID_SEARCH_RESULT_LIMIT
    rows = list(queryset[: limit + 1])
    has_more = len(rows) > limit
    return rows[:limit], has_more


def _agent_display_name(user):
    name = f"{user.first_name} {user.last_name}".strip()
    return name or user.email


@login_required(login_url='/login/')
def customer_search_api(request):
    q = request.GET.get('q', '').strip()
    qs = MyUser.objects.filter(role='Customer').order_by('first_name', 'last_name', 'email')
    if q:
        qs = qs.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(phone__icontains=q)
            | Q(email__icontains=q)
        )
    customers, has_more = _hybrid_search_slice(qs)
    return JsonResponse({
        'results': [
            {
                'id': c.id,
                'name': c.display_name,
                'sublabel': c.phone,
                'email': c.email,
            }
            for c in customers
        ],
        'has_more': has_more,
    })


@login_required(login_url='/login/')
def agent_search_api(request):
    if not _user_can_assign_tickets(request.user):
        return JsonResponse({'results': [], 'has_more': False})

    q = request.GET.get('q', '').strip()
    qs = MyUser.objects.filter(role='Field Agent').order_by('first_name', 'last_name', 'email')
    if q:
        qs = qs.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(email__icontains=q)
            | Q(phone__icontains=q)
        )
    agents, has_more = _hybrid_search_slice(qs)
    return JsonResponse({
        'results': [
            {
                'id': a.id,
                'name': _agent_display_name(a),
                'sublabel': a.email,
            }
            for a in agents
        ],
        'has_more': has_more,
    })


def _hybrid_initial_customer(customer_id):
    if not customer_id:
        return None
    customer = MyUser.objects.filter(pk=customer_id, role='Customer').first()
    if not customer:
        return None
    return {
        'value': customer.id,
        'name': customer.display_name,
        'sublabel': customer.phone,
    }


def _hybrid_initial_agent(agent_id):
    if not agent_id:
        return None
    agent = MyUser.objects.filter(pk=agent_id, role='Field Agent').first()
    if not agent:
        return None
    return {
        'value': agent.id,
        'name': _agent_display_name(agent),
        'sublabel': agent.email,
    }


@login_required(login_url='/login/')
def ticket_create_view(request):
    if not _user_can_create_tickets(request.user):
        messages.error(request, 'Only admins and receptionists can create tickets.')
        return redirect('home')

    customer_mode = 'existing'
    customer_form = CustomerForm(prefix='new_customer')
    can_assign = _user_can_assign_tickets(request.user)

    if request.method == "POST":
        from core.sms_debug import sms_debug

        sms_debug('ticket_create_page', 'post_received', can_assign=can_assign)
        customer_mode = request.POST.get('customer_mode', 'existing')
        form = TicketForm(request.POST, can_assign=can_assign)
        create_new_customer = customer_mode == 'new'

        if create_new_customer:
            customer_form = CustomerForm(request.POST, prefix='new_customer')
            if customer_form.is_valid() and form.is_valid():
                customer = customer_form.save()
                ticket = form.save(commit=False)
                ticket.customer = customer
                ticket = _save_ticket_with_attachment(
                    request, ticket, form=form, sms_source='ticket_create_page',
                )
                assigned_to = _apply_ticket_assignment(
                    ticket, form, request.user, sms_source='ticket_create_page',
                )
                messages.success(
                    request,
                    ticket_created_flash_message(
                        ticket, request, customer_name=customer.display_name,
                        assigned_to=assigned_to,
                    ),
                )
                return redirect(f"/tickets/{ticket.ticket_id}/")
            messages.error(request, "Please correct the errors below.")
        elif form.is_valid():
            ticket = form.save(commit=False)
            ticket = _save_ticket_with_attachment(
                request, ticket, form=form, sms_source='ticket_create_page',
            )
            assigned_to = _apply_ticket_assignment(
                ticket, form, request.user, sms_source='ticket_create_page',
            )
            messages.success(
                request,
                ticket_created_flash_message(ticket, request, assigned_to=assigned_to),
            )
            return redirect(f"/tickets/{ticket.ticket_id}/")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = TicketForm(can_assign=can_assign)

    customer_id = request.POST.get('customer') if request.method == 'POST' else None
    agent_id = request.POST.get('assigned_to') if request.method == 'POST' and can_assign else None

    return render(request, "core/ticket_form.html", {
        "form": form,
        "customer_form": customer_form,
        "customer_mode": customer_mode,
        "can_assign": can_assign,
        "customer_search_initial": _hybrid_initial_customer(customer_id),
        "agent_search_initial": _hybrid_initial_agent(agent_id),
    })

@login_required(login_url='/login/')
def ticket_detail_view(request, ticket_id):
    ticket = get_object_or_404(Ticket, ticket_id=ticket_id)
    
    # Process actions (POST requests)
    if request.method == "POST":
        action = request.POST.get('action')
        
        # 1. Post Comment
        if action == 'add_comment':
            comment_text = request.POST.get('comment', '').strip()
            if comment_text:
                TicketComments.objects.create(
                    ticket=ticket,
                    comment=comment_text,
                    commented_by=request.user
                )
                messages.success(request, "Comment added successfully.")
            else:
                messages.error(request, "Comment text cannot be empty.")
            return redirect(f"/tickets/{ticket.ticket_id}/")
            
        # 2. Update Status
        elif action == 'update_status':
            new_status = request.POST.get('status')
            if new_status in dict(Ticket.STATUS):
                ticket.status = new_status
                ticket.save()
                messages.success(request, f"Ticket status updated to {new_status}.")
            return redirect(f"/tickets/{ticket.ticket_id}/")
            
        # 3. Update Assignment
        elif action == 'update_assignment':
            from core.sms_debug import sms_debug

            sms_debug(
                'ticket_detail_page',
                'update_assignment_post',
                ticket_id=ticket.ticket_id,
                assigned_to_id=request.POST.get('assigned_to'),
            )
            if _user_can_assign_tickets(request.user):
                assigned_to_id = request.POST.get('assigned_to')
                if assigned_to_id:
                    assigned_user = MyUser.objects.filter(
                        id=assigned_to_id, role='Field Agent',
                    ).first()
                    if not assigned_user:
                        messages.error(
                            request,
                            'Please select a valid field agent.',
                        )
                    else:
                        from core.notifications import assign_ticket_to_agent
                        assign_ticket_to_agent(
                            ticket, assigned_user, source='ticket_detail_page',
                        )
                        messages.success(
                            request,
                            f"Ticket assigned to {assigned_user.email}.",
                        )
                else:
                    sms_debug(
                        'ticket_detail_page',
                        'assignment_cleared',
                        ticket_id=ticket.ticket_id,
                    )
                    TicketAssignment.objects.filter(ticket=ticket).delete()
                    messages.success(request, "Ticket assignment cleared.")
            else:
                messages.error(request, "You do not have permission to assign tickets.")
            return redirect(f"/tickets/{ticket.ticket_id}/")

        # 4. Add Attachment
        elif action == 'add_attachment':
            attachment_file = request.FILES.get('attachment')
            if attachment_file:
                TicketAttachments.objects.create(
                    ticket=ticket,
                    attachment=attachment_file
                )
                messages.success(request, "File attached successfully.")
            else:
                messages.error(request, "Please select a file to attach.")
            return redirect(f"/tickets/{ticket.ticket_id}/")

    # Fetch details, comments, and attachments
    comments = TicketComments.objects.filter(ticket=ticket).select_related(
        'commented_by',
    ).order_by('commented_at')
    attachments = TicketAttachments.objects.filter(ticket=ticket).order_by('uploaded_at')
    current_assignment = TicketAssignment.objects.filter(ticket=ticket).first()
    
    field_agents = MyUser.objects.filter(role='Field Agent').order_by(
        'first_name', 'last_name', 'email',
    )

    context = {
        'ticket': ticket,
        'comments': comments,
        'attachments': attachments,
        'assignment': current_assignment,
        'agents': field_agents,
        'statuses': Ticket.STATUS
    }
    return render(request, "core/ticket_detail.html", context)

def _build_user_assignment_rows(users):
    """Per-user matrix: category rows × ticket status columns."""
    user_ids = [u.id for u in users]
    status_order = [status for status, _ in Ticket.STATUS]
    if not user_ids:
        return []

    matrix_qs = (
        TicketAssignment.objects.filter(assigned_to_id__in=user_ids)
        .values(
            'assigned_to_id',
            'ticket__categories__id',
            'ticket__categories__name',
            'ticket__status',
        )
        .annotate(count=Count('ticket', distinct=True))
    )

    grid = defaultdict(lambda: defaultdict(dict))
    category_names = {}
    for row in matrix_qs:
        user_id = row['assigned_to_id']
        category_id = row['ticket__categories__id']
        if not category_id:
            continue
        category_names[category_id] = row['ticket__categories__name']
        grid[user_id][category_id][row['ticket__status']] = row['count']

    user_rows = []
    for user in users:
        table_rows = []
        total = 0
        user_grid = grid[user.id]

        for category_id in sorted(user_grid.keys(), key=lambda cid: category_names.get(cid, '')):
            cells = []
            row_total = 0
            for status in status_order:
                count = user_grid[category_id].get(status, 0)
                cells.append({'status': status, 'count': count})
                row_total += count
            if row_total:
                table_rows.append({
                    'category_name': category_names[category_id],
                    'cells': cells,
                    'row_total': row_total,
                })
                total += row_total

        user_rows.append({
            'user': user,
            'assignment_total': total,
            'assignment_table': table_rows,
        })
    return user_rows


@login_required(login_url='/login/')
def user_list_view(request):
    _require_admin(request.user)

    users = list(
        MyUser.objects.exclude(role='Customer').order_by('-date_joined')
    )
    user_rows = _build_user_assignment_rows(users)
    ticket_statuses = [status for status, _ in Ticket.STATUS]

    context = {
        'user_rows': user_rows,
        'ticket_statuses': ticket_statuses,
        'metrics': {
            'total': len(users),
            'admins': sum(1 for u in users if u.role == 'Admin'),
            'agents': sum(1 for u in users if u.role == 'Field Agent'),
            'receptionists': sum(1 for u in users if u.role == 'Receptionist'),
        },
    }
    return render(request, "core/user_list.html", context)

@login_required(login_url='/login/')
def user_create_view(request):
    _require_admin(request.user)
        
    if request.method == "POST":
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            
            # Elevate Admin user permissions
            if user.role == 'Admin':
                user.is_staff = True
                user.is_superuser = True
                
            user.save()
            messages.success(request, f"User {user.email} created successfully!")
            return redirect("user_list")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = UserCreateForm()
        
    return render(request, "core/user_form.html", {"form": form})

CUSTOMERS_PER_PAGE = 100


@login_required(login_url='/login/')
def customer_list_view(request):
    _require_admin_or_receptionist(request.user)
    search_query = request.GET.get('search', '').strip()
    customers_qs = MyUser.objects.filter(role='Customer').annotate(
        ticket_count=Count('customer_tickets'),
    ).order_by('-date_joined')

    if search_query:
        customers_qs = customers_qs.filter(
            Q(first_name__icontains=search_query)
            | Q(last_name__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(phone__icontains=search_query)
            | Q(address__icontains=search_query)
        )

    paginator = Paginator(customers_qs, CUSTOMERS_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj': page_obj,
        'customers': page_obj,
        'metrics': {
            'total_customers': MyUser.objects.filter(role='Customer').count(),
            'total_tickets': Ticket.objects.filter(customer__isnull=False).count(),
        },
        'search': search_query,
    }
    return render(request, "core/customer_list.html", context)

@login_required(login_url='/login/')
def customer_create_view(request):
    _require_admin_or_receptionist(request.user)

    if request.method == "POST":
        form = CustomerForm(request.POST)
        if form.is_valid():
            customer = form.save()
            portal_password = (form.cleaned_data.get('portal_password') or '').strip()
            if portal_password:
                messages.success(
                    request,
                    f"Customer '{customer.display_name}' added with portal login enabled.",
                )
            else:
                messages.success(
                    request,
                    f"Customer '{customer.display_name}' added. "
                    f"Portal login: phone + phone number as password.",
                )
            return redirect("customer_list")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = CustomerForm()

    return render(request, "core/customer_form.html", {"form": form})

@login_required(login_url='/login/')
def customer_detail_view(request, pk):
    _require_admin_or_receptionist(request.user)
    customer = get_object_or_404(MyUser, pk=pk, role='Customer')
    tickets = Ticket.objects.filter(customer=customer).order_by('-created_at')

    open_count = tickets.filter(status='Open').count()
    in_progress_count = tickets.filter(status='In Progress').count()
    resolved_count = tickets.filter(status__in=['Resolved', 'Closed']).count()

    context = {
        'customer': customer,
        'tickets': tickets,
        'metrics': {
            'total': tickets.count(),
            'open': open_count,
            'in_progress': in_progress_count,
            'resolved': resolved_count,
        }
    }
    return render(request, "core/customer_detail.html", context)
