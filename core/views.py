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
from .models import (
    MyUser, Ticket, TicketCategory, TicketAssignment, TicketComments,
    TicketAttachments, NetworkRouter, CustomerHomeRouter,
)
from .ticket_urls import ticket_created_flash_message
from .forms import (
    TicketForm, CommentForm, AttachmentForm, UserCreateForm, CustomerForm,
    ProfileForm, ProfilePasswordForm, NetworkRouterForm, CustomerHomeRouterForm,
)


def redirect_after_login(user):
    if user.role == 'Customer':
        return redirect('portal_ticket_list')
    target = 'admin_dashboard' if user.role == 'Admin' else 'ticket_list'
    if settings.DEBUG:
        return redirect(target)
    return redirect(host_reverse(target, host='tickets'))


def redirect_to_portal_home():
    """Send authenticated staff to the ticket list."""
    if settings.DEBUG:
        return redirect('ticket_list')
    return redirect(host_reverse('ticket_list', host='tickets'))


def landing_page(request):
    if request.user.is_authenticated:
        if request.user.role == 'Customer':
            return redirect('portal_ticket_list')
        if settings.DEBUG:
            return redirect_after_login(request.user)
    return render(request, "core/landing.html")


@login_required(login_url='/login/')
def home_redirect_view(request):
    """Legacy /home/ — admins to analytics, everyone else to ticket list."""
    if request.user.role == 'Customer':
        return redirect('portal_ticket_list')
    if request.user.role == 'Admin':
        return redirect('admin_dashboard')
    return redirect('ticket_list')


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
def ticket_list_view(request):
    if request.user.role == 'Customer':
        return redirect('portal_ticket_list')
    is_agent = request.user.role == 'Field Agent'
    
    # Fetch filter params
    status_filter = request.GET.get('status', '')
    priority_filter = request.GET.get('priority', '')
    category_filter = request.GET.get('category', '')
    search_query = request.GET.get('search', '')

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

    # Default: hide only Resolved/Closed; show all other statuses unless a filter is applied
    if status_filter == '':
        tickets = tickets.exclude(status__in=RESOLVED_STATUSES)
    elif status_filter == 'resolved_closed':
        tickets = tickets.filter(status__in=RESOLVED_STATUSES)
    else:
        # A specific status was requested (Open, In Progress, On Hold, Resolved, Closed)
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


# Backwards-compatible alias
home_view = ticket_list_view


@login_required(login_url='/login/')
def admin_dashboard_view(request):
    """Admin analytics: users, customers, ticket usage, router LOS / unreachable."""
    if request.user.role != 'Admin':
        raise PermissionDenied

    import json
    from datetime import timedelta

    from django.db.models import Sum
    from django.db.models.functions import TruncDate
    from django.utils import timezone

    days = request.GET.get('days', '30')
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 30
    if days not in (7, 30, 90):
        days = 30

    now = timezone.now()
    since = now - timedelta(days=days)
    since_7d = now - timedelta(days=7)
    prev_since = since - timedelta(days=days)

    customers = MyUser.objects.filter(role='Customer')
    staff = MyUser.objects.exclude(role='Customer')

    tickets_qs = Ticket.objects.all()
    open_statuses = ['Open', 'In Progress', 'On Hold']

    los_q = (
        Q(categories__name__icontains='LOS')
        | Q(categories__name__icontains='Line Of Sight')
        | Q(categories__name__icontains='line of sight')
    )
    los_open = (
        tickets_qs.filter(status__in=open_statuses)
        .filter(los_q)
        .distinct()
        .count()
    )

    tickets_period = tickets_qs.filter(created_at__gte=since).count()
    tickets_prev = tickets_qs.filter(created_at__gte=prev_since, created_at__lt=since).count()
    cust_period = customers.filter(date_joined__gte=since).count()
    cust_prev = customers.filter(date_joined__gte=prev_since, date_joined__lt=since).count()

    def _trend(curr, prev):
        if prev <= 0:
            return {'pct': 100 if curr else 0, 'dir': 'up' if curr else 'flat'}
        pct = round((curr - prev) / prev * 100, 1)
        return {'pct': abs(pct), 'dir': 'up' if pct > 0 else ('down' if pct < 0 else 'flat')}

    category_breakdown = list(
        TicketCategory.objects.annotate(
            open_count=Count(
                'tickets',
                filter=Q(tickets__status__in=open_statuses),
                distinct=True,
            ),
            total_count=Count('tickets', distinct=True),
        )
        .order_by('-open_count', 'name')[:6]
    )
    cat_max = max((c.open_count for c in category_breakdown), default=1) or 1
    category_open_total = sum(c.open_count for c in category_breakdown)

    routers = NetworkRouter.objects.filter(is_active=True)
    router_stats = {
        'total': routers.count(),
        'online': routers.filter(status=NetworkRouter.STATUS_ONLINE).count(),
        'unreachable': routers.filter(status=NetworkRouter.STATUS_UNREACHABLE).count(),
        'los': routers.filter(status=NetworkRouter.STATUS_LOS).count(),
        'unknown': routers.filter(status=NetworkRouter.STATUS_UNKNOWN).count(),
    }
    problem_routers = list(
        routers.filter(
            status__in=[
                NetworkRouter.STATUS_UNREACHABLE,
                NetworkRouter.STATUS_LOS,
            ]
        ).order_by('status', 'name')[:12]
    )

    mpesa = _mpesa_stats(since, prev_since)

    agent_workload = list(
        MyUser.objects.filter(role='Field Agent')
        .annotate(
            open_assigned=Count(
                'ticketassignment',
                filter=Q(ticketassignment__ticket__status__in=open_statuses),
                distinct=True,
            )
        )
        .order_by('-open_assigned', 'first_name')[:8]
    )

    # Daily ticket volume for chart
    daily_rows = (
        tickets_qs.filter(created_at__gte=since)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(c=Count('id'))
        .order_by('day')
    )
    daily_map = {r['day']: r['c'] for r in daily_rows}
    chart_labels = []
    chart_tickets = []
    chart_dates = []
    for i in range(days - 1, -1, -1):
        d = (now - timedelta(days=i)).date()
        chart_dates.append(d)
        chart_labels.append(d.strftime('%b %d'))
        chart_tickets.append(daily_map.get(d, 0))

    # Top agents as multi-series cumulative assignment trend
    agent_trend_colors = ['#3B82F6', '#6EE7B7', '#FDBA74']
    top_trend_agents = agent_workload[:3]
    agent_series = []
    for idx, agent in enumerate(top_trend_agents):
        assign_rows = (
            TicketAssignment.objects.filter(
                assigned_to=agent,
                assigned_at__gte=since,
            )
            .annotate(day=TruncDate('assigned_at'))
            .values('day')
            .annotate(c=Count('id'))
            .order_by('day')
        )
        day_map = {r['day']: r['c'] for r in assign_rows}
        cumulative = []
        running = 0
        for d in chart_dates:
            running += day_map.get(d, 0)
            cumulative.append(running)
        label = (agent.first_name or '').strip() or agent.display_name
        if len(label) > 18:
            label = label[:16] + '…'
        agent_series.append({
            'name': label,
            'color': agent_trend_colors[idx % len(agent_trend_colors)],
            'data': cumulative,
            'open': int(agent.open_assigned),
        })

    focus_index = max(0, min(len(chart_labels) - 1, int(len(chart_labels) * 0.55)))
    focus_value = 0
    focus_delta_pct = 0.0
    if agent_series:
        top_data = agent_series[0]['data']
        focus_value = int(top_data[focus_index])
        prev_value = int(top_data[focus_index - 1]) if focus_index > 0 else focus_value
        if prev_value > 0:
            focus_delta_pct = round((focus_value - prev_value) / prev_value * 100, 1)
        elif focus_value > 0:
            focus_delta_pct = 100.0

    tickets = {
            'total': tickets_qs.count(),
            'open': tickets_qs.filter(status='Open').count(),
            'in_progress': tickets_qs.filter(status='In Progress').count(),
            'on_hold': tickets_qs.filter(status='On Hold').count(),
            'resolved': tickets_qs.filter(status='Resolved').count(),
            'closed': tickets_qs.filter(status='Closed').count(),
            'created_period': tickets_period,
            'created_trend': _trend(tickets_period, tickets_prev),
            'los_open': los_open,
            'active': tickets_qs.filter(status__in=open_statuses).count(),
        }

    def _status_snapshot(qs):
        open_n = qs.filter(status='Open').count()
        progress_n = qs.filter(status='In Progress').count()
        resolved_n = qs.filter(status__in=['Resolved', 'Closed']).count()
        total_n = qs.count()
        done_pct = round(resolved_n / total_n * 100) if total_n else 0
        return {
            'total': total_n,
            'donePct': done_pct,
            'items': [
                {'key': 'open', 'label': 'Open', 'count': open_n, 'color': '#8B5CF6'},
                {'key': 'progress', 'label': 'In Progress', 'count': progress_n, 'color': '#1F2937'},
                {'key': 'resolved', 'label': 'Resolved', 'count': resolved_n, 'color': '#22D3EE'},
            ],
        }

    ticket_status_by_period = {
        'week': _status_snapshot(tickets_qs.filter(created_at__gte=now - timedelta(days=7))),
        'month': _status_snapshot(tickets_qs.filter(created_at__gte=now - timedelta(days=30))),
        'year': _status_snapshot(tickets_qs.filter(created_at__gte=now - timedelta(days=365))),
    }
    default_status_period = 'week' if days == 7 else ('year' if days == 90 else 'month')

    context = {
        'days': days,
        'users': {
            'customers': customers.count(),
            'admins': staff.filter(role='Admin').count(),
            'receptionists': staff.filter(role='Receptionist').count(),
            'agents': staff.filter(role='Field Agent').count(),
            'staff_total': staff.count(),
            'customers_joined_7d': customers.filter(date_joined__gte=since_7d).count(),
            'customers_joined_period': cust_period,
            'customers_trend': _trend(cust_period, cust_prev),
        },
        'tickets': tickets,
        'category_breakdown': category_breakdown,
        'cat_max': cat_max,
        'category_open_total': category_open_total,
        'router_stats': router_stats,
        'problem_routers': problem_routers,
        'mpesa': mpesa,
        'agent_workload': agent_workload,
        'status_period': default_status_period,
        'chart_json': {
            'labels': chart_labels,
            'tickets': chart_tickets,
            'router': [
                router_stats['online'],
                router_stats['unreachable'],
                router_stats['los'],
                router_stats['unknown'],
            ],
            'ticketStatus': [
                tickets['open'],
                tickets['in_progress'],
                tickets['on_hold'],
                tickets['resolved'],
                tickets['closed'],
            ],
            'ticketStatusPeriods': ticket_status_by_period,
            'statusPeriod': default_status_period,
            'categories': {
                'labels': [c.name for c in category_breakdown],
                'values': [int(c.open_count) for c in category_breakdown],
                'total': int(category_open_total),
            },
            'agentWorkload': {
                'labels': chart_labels,
                'series': agent_series,
                'focusIndex': focus_index,
                'focusValue': focus_value,
                'focusDeltaPct': focus_delta_pct,
            },
        },
    }
    return render(request, 'core/admin_dashboard.html', context)


def _mpesa_stats(since, prev_since=None):
    from datetime import timedelta
    stats = {
        'success_period': 0,
        'pending': 0,
        'failed_period': 0,
        'amount_period': 0,
        'amount_prev': 0,
        'failed_amount_period': 0,
        'failed_amount_prev': 0,
        'success_prev': 0,
        'recent': [],
        'daily_amounts': [],
        'daily_failed_amounts': [],
        'daily_labels': [],
        'month_income': 0,
        'month_income_prev': 0,
        'year_income': 0,
        'year_income_prev': 0,
        'month_expenditure': 0,
        'month_expenditure_prev': 0,
        'year_expenditure': 0,
        'year_expenditure_prev': 0,
    }
    try:
        from django.db.models import Count, Sum
        from django.db.models.functions import Coalesce, TruncDate
        from django.utils import timezone

        from billing.models import MpesaPayment

        qs = MpesaPayment.objects.all()
        # Prefer completed_at for when money landed (mock seed dates live here;
        # created_at is auto_now_add and often all "today" after bulk_create).
        paid = qs.filter(status='success').annotate(
            paid_at=Coalesce('completed_at', 'created_at'),
        )

        stats['pending'] = qs.filter(status='pending').count()
        stats['success_period'] = paid.filter(paid_at__gte=since).count()
        stats['failed_period'] = qs.filter(
            status__in=['failed', 'cancelled'], created_at__gte=since,
        ).count()
        stats['amount_period'] = (
            paid.filter(paid_at__gte=since).aggregate(s=Sum('amount'))['s']
            or 0
        )
        stats['failed_amount_period'] = (
            qs.filter(
                status__in=['failed', 'cancelled'], created_at__gte=since,
            ).aggregate(s=Sum('amount'))['s']
            or 0
        )
        if prev_since is not None:
            stats['amount_prev'] = (
                paid.filter(paid_at__gte=prev_since, paid_at__lt=since)
                .aggregate(s=Sum('amount'))['s']
                or 0
            )
            stats['failed_amount_prev'] = (
                qs.filter(
                    status__in=['failed', 'cancelled'],
                    created_at__gte=prev_since,
                    created_at__lt=since,
                ).aggregate(s=Sum('amount'))['s']
                or 0
            )
            stats['success_prev'] = paid.filter(
                paid_at__gte=prev_since, paid_at__lt=since,
            ).count()
        stats['recent'] = list(
            qs.select_related('customer').order_by('-created_at')[:10]
        )

        daily = (
            paid.filter(paid_at__gte=since)
            .annotate(day=TruncDate('paid_at'))
            .values('day')
            .annotate(total=Sum('amount'), c=Count('id'))
            .order_by('day')
        )
        dmap = {r['day']: float(r['total'] or 0) for r in daily}
        failed_daily = (
            qs.filter(status__in=['failed', 'cancelled'], created_at__gte=since)
            .annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(total=Sum('amount'))
            .order_by('day')
        )
        fmap = {r['day']: float(r['total'] or 0) for r in failed_daily}
        now = timezone.now()
        # Infer day count from since
        day_count = max((now.date() - since.date()).days + 1, 1)
        day_count = min(day_count, 90)
        for i in range(day_count - 1, -1, -1):
            d = (now - timedelta(days=i)).date()
            stats['daily_labels'].append(d.strftime('%b %d'))
            stats['daily_amounts'].append(dmap.get(d, 0))
            stats['daily_failed_amounts'].append(fmap.get(d, 0))

        # Monthly / yearly rollups for the income vs expenditure card
        month_since = now - timedelta(days=30)
        month_prev_since = month_since - timedelta(days=30)
        year_since = now - timedelta(days=365)
        year_prev_since = year_since - timedelta(days=365)

        def _sum_success(start, end=None):
            q = paid.filter(paid_at__gte=start)
            if end is not None:
                q = q.filter(paid_at__lt=end)
            return q.aggregate(s=Sum('amount'))['s'] or 0

        def _sum_failed(start, end=None):
            q = qs.filter(status__in=['failed', 'cancelled'], created_at__gte=start)
            if end is not None:
                q = q.filter(created_at__lt=end)
            return q.aggregate(s=Sum('amount'))['s'] or 0

        stats['month_income'] = _sum_success(month_since)
        stats['month_income_prev'] = _sum_success(month_prev_since, month_since)
        stats['year_income'] = _sum_success(year_since)
        stats['year_income_prev'] = _sum_success(year_prev_since, year_since)
        stats['month_expenditure'] = _sum_failed(month_since)
        stats['month_expenditure_prev'] = _sum_failed(month_prev_since, month_since)
        stats['year_expenditure'] = _sum_failed(year_since)
        stats['year_expenditure_prev'] = _sum_failed(year_prev_since, year_since)
    except Exception:
        pass
    return stats


def _money_trend(curr, prev):
    curr = float(curr or 0)
    prev = float(prev or 0)
    if prev > 0:
        pct = round((curr - prev) / prev * 100, 1)
        return {
            'pct': abs(pct),
            'dir': 'up' if pct > 0 else ('down' if pct < 0 else 'flat'),
            'delta': abs(curr - prev),
        }
    return {
        'pct': 100 if curr else 0,
        'dir': 'up' if curr else 'flat',
        'delta': curr,
    }


def _expenditure_stats(since, day_labels_dates=None):
    """Daily + monthly/yearly totals from billing.Expenditure."""
    from datetime import timedelta

    from django.db.models import Sum
    from django.db.models.functions import TruncDate
    from django.utils import timezone

    stats = {
        'daily_amounts': [],
        'amount_period': 0,
        'amount_prev': 0,
        'month': 0,
        'month_prev': 0,
        'year': 0,
        'year_prev': 0,
    }
    try:
        from billing.models import Expenditure

        qs = Expenditure.objects.all()
        now = timezone.now()
        prev_since = since - (now - since)

        stats['amount_period'] = (
            qs.filter(occurred_at__gte=since).aggregate(s=Sum('amount'))['s'] or 0
        )
        stats['amount_prev'] = (
            qs.filter(occurred_at__gte=prev_since, occurred_at__lt=since)
            .aggregate(s=Sum('amount'))['s']
            or 0
        )

        month_since = now - timedelta(days=30)
        month_prev_since = month_since - timedelta(days=30)
        year_since = now - timedelta(days=365)
        year_prev_since = year_since - timedelta(days=365)

        def _sum(start, end=None):
            q = qs.filter(occurred_at__gte=start)
            if end is not None:
                q = q.filter(occurred_at__lt=end)
            return q.aggregate(s=Sum('amount'))['s'] or 0

        stats['month'] = _sum(month_since)
        stats['month_prev'] = _sum(month_prev_since, month_since)
        stats['year'] = _sum(year_since)
        stats['year_prev'] = _sum(year_prev_since, year_since)

        daily = (
            qs.filter(occurred_at__gte=since)
            .annotate(day=TruncDate('occurred_at'))
            .values('day')
            .annotate(total=Sum('amount'))
            .order_by('day')
        )
        dmap = {r['day']: float(r['total'] or 0) for r in daily}

        if day_labels_dates:
            dates = day_labels_dates
        else:
            day_count = max((now.date() - since.date()).days + 1, 1)
            day_count = min(day_count, 90)
            dates = [(now - timedelta(days=i)).date() for i in range(day_count - 1, -1, -1)]

        stats['daily_amounts'] = [dmap.get(d, 0) for d in dates]
    except Exception:
        pass
    return stats


@login_required(login_url='/login/')
def finance_dashboard_view(request):
    """Finance analytics for M-Pesa collections and payment health."""
    if request.user.role not in ('Admin', 'Receptionist'):
        raise PermissionDenied

    import json
    from datetime import timedelta
    from decimal import Decimal

    from django.utils import timezone

    days = request.GET.get('days', '30')
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 30
    if days not in (7, 30, 90):
        days = 30

    now = timezone.now()
    since = now - timedelta(days=days)
    prev_since = since - timedelta(days=days)

    mpesa = _mpesa_stats(since, prev_since)
    amount = Decimal(str(mpesa['amount_period'] or 0))
    prev_amount = Decimal(str(mpesa['amount_prev'] or 0))
    if prev_amount > 0:
        pct = float((amount - prev_amount) / prev_amount * 100)
        amount_trend = {
            'pct': round(abs(pct), 1),
            'dir': 'up' if pct > 0 else ('down' if pct < 0 else 'flat'),
        }
    else:
        amount_trend = {'pct': 100 if amount else 0, 'dir': 'up' if amount else 'flat'}

    success = mpesa['success_period']
    failed = mpesa['failed_period']
    total_done = success + failed
    success_rate = round(success / total_done * 100, 1) if total_done else 0

    # Align expenditure daily buckets with income chart dates
    income_series = [float(x or 0) for x in mpesa['daily_amounts']]
    chart_dates = []
    day_count = len(mpesa['daily_labels']) or days
    for i in range(day_count - 1, -1, -1):
        chart_dates.append((now - timedelta(days=i)).date())
    exp_stats = _expenditure_stats(since, day_labels_dates=chart_dates)
    expense_series = [float(x or 0) for x in exp_stats['daily_amounts']]

    month_income = float(mpesa['month_income'] or 0)
    year_income = float(mpesa['year_income'] or 0)
    month_exp = float(exp_stats['month'] or 0)
    year_exp = float(exp_stats['year'] or 0)
    income_month_trend = _money_trend(month_income, mpesa['month_income_prev'])
    income_year_trend = _money_trend(year_income, mpesa['year_income_prev'])
    exp_month_trend = _money_trend(month_exp, exp_stats['month_prev'])

    def _fmt_kes(n):
        return f'{n:,.0f}'

    context = {
        'days': days,
        'mpesa': mpesa,
        'amount_trend': amount_trend,
        'success_rate': success_rate,
        'income_report': {
            'month': _fmt_kes(month_income),
            'year': _fmt_kes(year_income),
            'month_exp': _fmt_kes(month_exp),
            'year_exp': _fmt_kes(year_exp),
            'month_trend': income_month_trend,
            'year_trend': income_year_trend,
            'exp_trend': exp_month_trend,
            'month_delta': _fmt_kes(income_month_trend['delta']),
            'year_delta': _fmt_kes(income_year_trend['delta']),
            'exp_delta': _fmt_kes(exp_month_trend['delta']),
        },
        'chart_json': {
            'labels': mpesa['daily_labels'],
            'amounts': income_series,
            'expenditure': expense_series,
            'status': [success, mpesa['pending'], failed],
            'incomeReport': {
                'month': month_income,
                'year': year_income,
                'monthExp': month_exp,
                'yearExp': year_exp,
            },
        },
    }
    return render(request, 'core/finance_dashboard.html', context)


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
    # NOTE: notification is NOT sent here — the calling view sends it after
    # resolving the agent assignment so we can merge both into one SMS.
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


def _apply_ticket_assignment(ticket, form, user, sms_source='ticket_create_page',
                             at_creation=False):
    from core.sms_debug import sms_debug
    from core.models import TicketAssignment

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

    if at_creation:
        # Only persist the DB record — notifications are handled entirely by
        # notify_ticket_created(agent=assigned_to) called right after this,
        # which sends one combined customer SMS + one agent SMS.
        TicketAssignment.objects.filter(ticket=ticket).delete()
        TicketAssignment.objects.create(ticket=ticket, assigned_to=assigned_to)
        sms_debug(sms_source, 'assign_db_only_at_creation', ticket_id=ticket.ticket_id)
    else:
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
        return redirect('ticket_list')

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
                    at_creation=True,
                )
                from core.notifications import notify_ticket_created
                from core.sms_report import stash_sms_report
                sms_report = notify_ticket_created(
                    ticket, source='ticket_create_page', agent=assigned_to,
                )
                stash_sms_report(request, sms_report)
                if sms_report.overall in ('failed', 'partial', 'skipped'):
                    messages.warning(
                        request,
                        'Ticket saved, but SMS notifications need attention. '
                        'See the SMS activity report.',
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
                at_creation=True,
            )
            from core.notifications import notify_ticket_created
            from core.sms_report import stash_sms_report
            sms_report = notify_ticket_created(
                ticket, source='ticket_create_page', agent=assigned_to,
            )
            stash_sms_report(request, sms_report)
            if sms_report.overall in ('failed', 'partial', 'skipped'):
                messages.warning(
                    request,
                    'Ticket saved, but SMS notifications need attention. '
                    'See the SMS activity report.',
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
                        from core.sms_report import stash_sms_report
                        sms_report = assign_ticket_to_agent(
                            ticket, assigned_user, source='ticket_detail_page',
                        )
                        stash_sms_report(request, sms_report)
                        if sms_report.overall in ('failed', 'partial', 'skipped'):
                            messages.warning(
                                request,
                                'Assignment saved, but SMS notifications need attention. '
                                'See the SMS activity report.',
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

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_home_router':
            form = CustomerHomeRouterForm(request.POST)
            if form.is_valid():
                home = form.save(commit=False)
                home.customer = customer
                home.save()
                messages.success(
                    request,
                    f"Home router '{home.display_name}' added for {customer.display_name}.",
                )
            else:
                for err in form.non_field_errors():
                    messages.error(request, err)
                for field, errs in form.errors.items():
                    if field == '__all__':
                        continue
                    messages.error(request, f'{field}: {errs[0]}')
            return redirect('customer_detail', pk=customer.pk)

        if action == 'retire_home_router':
            home_id = request.POST.get('home_router_id')
            home = get_object_or_404(
                CustomerHomeRouter, pk=home_id, customer=customer,
            )
            home.is_active = False
            home.save(update_fields=['is_active', 'updated_at'])
            messages.success(request, f"Home router '{home.display_name}' marked inactive.")
            return redirect('customer_detail', pk=customer.pk)

    tickets = Ticket.objects.filter(customer=customer).order_by('-created_at')

    open_count = tickets.filter(status='Open').count()
    in_progress_count = tickets.filter(status='In Progress').count()
    resolved_count = tickets.filter(status__in=['Resolved', 'Closed']).count()

    subscription = None
    network_account = None
    invoices = []
    payments = []
    finance_history = []
    finance = {
        'collected': 0,
        'pending': 0,
        'invoiced': 0,
        'outstanding': 0,
        'payment_count': 0,
    }
    try:
        from django.db.models import Sum

        from billing.models import Invoice, MpesaPayment, NetworkServiceAccount, Subscription

        subscription = (
            Subscription.objects.filter(customer=customer)
            .select_related('plan')
            .order_by('-started_at')
            .first()
        )
        network_account = (
            NetworkServiceAccount.objects.filter(customer=customer)
            .select_related('router')
            .first()
        )
        invoices = list(
            Invoice.objects.filter(subscription__customer=customer)
            .select_related('subscription__plan')
            .order_by('-due_at')[:20]
        )
        pay_qs = MpesaPayment.objects.filter(
            Q(customer=customer) | Q(phone=customer.phone)
        ).distinct().order_by('-created_at')
        payments = list(pay_qs[:30])
        finance['payment_count'] = pay_qs.count()
        finance['collected'] = (
            pay_qs.filter(status='success').aggregate(s=Sum('amount'))['s'] or 0
        )
        finance['pending'] = (
            pay_qs.filter(status='pending').aggregate(s=Sum('amount'))['s'] or 0
        )
        inv_qs = Invoice.objects.filter(subscription__customer=customer)
        finance['invoiced'] = inv_qs.aggregate(s=Sum('amount_due'))['s'] or 0
        finance['outstanding'] = (
            inv_qs.exclude(status__in=['paid', 'void'])
            .aggregate(s=Sum('amount_due'))['s']
            or 0
        ) - (
            inv_qs.exclude(status__in=['paid', 'void'])
            .aggregate(s=Sum('amount_paid'))['s']
            or 0
        )
        finance_history = []
        for p in payments:
            finance_history.append({
                'kind': 'payment',
                'sort_at': p.completed_at or p.created_at,
                'payment': p,
            })
        for inv in invoices:
            finance_history.append({
                'kind': 'invoice',
                'sort_at': inv.due_at or inv.created_at,
                'invoice': inv,
            })
        finance_history.sort(
            key=lambda row: row['sort_at'] or customer.date_joined,
            reverse=True,
        )
    except Exception:
        finance_history = []
        network_account = None

    home_routers = list(
        CustomerHomeRouter.objects.filter(customer=customer).order_by(
            '-is_active', '-installed_at', '-id',
        )
    )
    home_router_form = CustomerHomeRouterForm(initial={'is_active': True})

    context = {
        'customer': customer,
        'tickets': tickets,
        'subscription': subscription,
        'network_account': network_account,
        'home_routers': home_routers,
        'home_router_form': home_router_form,
        'invoices': invoices,
        'payments': payments,
        'finance': finance,
        'finance_history': finance_history,
        'metrics': {
            'total': tickets.count(),
            'open': open_count,
            'in_progress': in_progress_count,
            'resolved': resolved_count,
        },
    }
    return render(request, "core/customer_detail.html", context)


@login_required(login_url='/login/')
def router_list_view(request):
    _require_admin(request.user)

    search_query = (request.GET.get('search') or '').strip()
    routers_qs = NetworkRouter.objects.all().order_by('name')
    if search_query:
        routers_qs = routers_qs.filter(
            Q(name__icontains=search_query)
            | Q(location__icontains=search_query)
            | Q(api_host__icontains=search_query)
            | Q(ip_address__icontains=search_query)
        )

    all_routers = list(NetworkRouter.objects.all())
    metrics = {
        'total': len(all_routers),
        'active': sum(1 for r in all_routers if r.is_active),
        'with_api': sum(1 for r in all_routers if r.has_api_credentials()),
        'default': sum(1 for r in all_routers if r.is_default and r.is_active),
    }

    return render(request, 'core/router_list.html', {
        'routers': routers_qs,
        'metrics': metrics,
        'search': search_query,
    })


@login_required(login_url='/login/')
def router_create_view(request):
    _require_admin(request.user)

    if request.method == 'POST':
        form = NetworkRouterForm(request.POST)
        if form.is_valid():
            router = form.save()
            messages.success(
                request,
                f"Router '{router.name}' added"
                f"{' and set as default' if router.is_default else ''}.",
            )
            return redirect('router_list')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = NetworkRouterForm(initial={
            'status': NetworkRouter.STATUS_UNKNOWN,
            'is_active': True,
            'api_ssl': True,
            'api_verify_ssl': False,
        })

    return render(request, 'core/router_form.html', {
        'form': form,
        'title': 'Add Network Router',
        'submit_label': 'Save Router',
        'is_edit': False,
    })


@login_required(login_url='/login/')
def router_edit_view(request, pk):
    _require_admin(request.user)
    router = get_object_or_404(NetworkRouter, pk=pk)

    if request.method == 'POST':
        form = NetworkRouterForm(request.POST, instance=router)
        if form.is_valid():
            router = form.save()
            messages.success(request, f"Router '{router.name}' updated.")
            return redirect('router_list')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = NetworkRouterForm(instance=router)

    return render(request, 'core/router_form.html', {
        'form': form,
        'title': f'Edit Router — {router.name}',
        'submit_label': 'Update Router',
        'is_edit': True,
        'router': router,
    })
