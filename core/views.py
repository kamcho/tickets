from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from .models import MyUser, Ticket, TicketCategory, TicketAssignment, TicketComments, TicketAttachments
from .forms import TicketForm, CommentForm, AttachmentForm, UserCreateForm

def login_view(request):
    if request.user.is_authenticated:
        return redirect("/")
        
    if request.method == "POST":
        email = request.POST.get("username")  # email is passed as username field
        password = request.POST.get("password")

        user = authenticate(
            request,
            username=email,
            password=password
        )

        if user is not None:
            login(request, user)
            messages.success(request, f"Welcome back, {user.email}!")
            return redirect("/")
        else:
            messages.error(request, "Invalid email or password")

    return render(request, "core/login.html")

@login_required(login_url='/login/')
def logout_view(request):
    if request.method == "POST":
        logout(request)
        messages.info(request, "You have been logged out successfully.")
    return redirect("/login/")

@login_required(login_url='/login/')
def home_view(request):
    is_agent = request.user.role == 'Field Agent'
    
    # Fetch filter params
    status_filter = request.GET.get('status', '')
    priority_filter = request.GET.get('priority', '')
    category_filter = request.GET.get('category', '')
    search_query = request.GET.get('search', '')

    tickets = Ticket.objects.all().order_by('-created_at')

    # If user is a Field Agent, filter for their assignments by default
    if is_agent:
        tickets = tickets.filter(ticketassignment__assigned_to=request.user)
        # Default view for agents shows only Open & In Progress
        if not status_filter and 'all_status' not in request.GET:
            tickets = tickets.filter(status__in=['Open', 'In Progress'])
            status_filter = 'active'

    # Apply filters
    if status_filter and status_filter != 'active':
        tickets = tickets.filter(status=status_filter)
    if priority_filter:
        tickets = tickets.filter(priority=priority_filter)
    if category_filter:
        tickets = tickets.filter(category_id=category_filter)
    if search_query:
        tickets = tickets.filter(
            Q(ticket_id__icontains=search_query) |
            Q(subject__icontains=search_query) |
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

@login_required(login_url='/login/')
def ticket_create_view(request):
    if request.method == "POST":
        form = TicketForm(request.POST)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.save() # This triggers the custom save override to generate ticket_id
            
            # Handle attachment if uploaded
            attachment_file = request.FILES.get('attachment')
            if attachment_file:
                TicketAttachments.objects.create(
                    ticket=ticket,
                    attachment=attachment_file
                )
                
            messages.success(request, f"Ticket {ticket.ticket_id} created successfully!")
            return redirect(f"/tickets/{ticket.ticket_id}/")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = TicketForm()

    return render(request, "core/ticket_form.html", {"form": form})

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
            # Only Admin and Receptionist can assign tickets
            if request.user.role in ['Admin', 'Receptionist'] or request.user.is_staff:
                assigned_to_id = request.POST.get('assigned_to')
                if assigned_to_id:
                    assigned_user = get_object_or_404(MyUser, id=assigned_to_id)
                    # Remove any existing assignments for this ticket
                    TicketAssignment.objects.filter(ticket=ticket).delete()
                    # Create new assignment
                    TicketAssignment.objects.create(
                        ticket=ticket,
                        assigned_to=assigned_user
                    )
                    messages.success(request, f"Ticket assigned to {assigned_user.email}.")
                else:
                    # Clear assignment
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
    comments = TicketComments.objects.filter(ticket=ticket).order_by('commented_at')
    attachments = TicketAttachments.objects.filter(ticket=ticket).order_by('uploaded_at')
    current_assignment = TicketAssignment.objects.filter(ticket=ticket).first()
    
    # User lists for assignment dropdown
    all_agents = MyUser.objects.all()
    
    context = {
        'ticket': ticket,
        'comments': comments,
        'attachments': attachments,
        'assignment': current_assignment,
        'agents': all_agents,
        'statuses': Ticket.STATUS
    }
    return render(request, "core/ticket_detail.html", context)

@login_required(login_url='/login/')
def user_list_view(request):
    if request.user.role != 'Admin':
        messages.error(request, "Access denied. Only Admins can manage users.")
        return redirect("/")
    
    users = MyUser.objects.all().order_by('-date_joined')
    
    # Quick metrics
    total_users = users.count()
    admins_count = users.filter(role='Admin').count()
    agents_count = users.filter(role='Field Agent').count()
    receptionists_count = users.filter(role='Receptionist').count()
    
    context = {
        'users': users,
        'metrics': {
            'total': total_users,
            'admins': admins_count,
            'agents': agents_count,
            'receptionists': receptionists_count,
        }
    }
    return render(request, "core/user_list.html", context)

@login_required(login_url='/login/')
def user_create_view(request):
    if request.user.role != 'Admin':
        messages.error(request, "Access denied. Only Admins can manage users.")
        return redirect("/")
        
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
