"""Platform super-admin: ISP vendor (tenant) management."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from core.forms import VendorForm
from core.models import Vendor
from core.tenancy import require_platform_superadmin

User = get_user_model()


def _vendor_metrics():
    return (
        Vendor.objects.annotate(
            staff_count=Count(
                'users',
                filter=Q(users__role__in=('Admin', 'Receptionist', 'Field Agent')),
                distinct=True,
            ),
            customer_count=Count(
                'users',
                filter=Q(users__role='Customer'),
                distinct=True,
            ),
            ticket_count=Count('tickets', distinct=True),
        )
        .order_by('name')
    )


@login_required(login_url='/login/')
def vendor_list_view(request):
    require_platform_superadmin(request)
    vendors = _vendor_metrics()
    return render(request, 'core/vendor_list.html', {
        'vendors': vendors,
        'metrics': {
            'total': vendors.count(),
            'active': vendors.filter(is_active=True).count(),
        },
    })


@login_required(login_url='/login/')
def vendor_create_view(request):
    require_platform_superadmin(request)
    if request.method == 'POST':
        form = VendorForm(request.POST)
        if form.is_valid():
            vendor = form.save()
            messages.success(request, f'Vendor "{vendor.name}" created.')
            return redirect('vendor_list')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = VendorForm()
    return render(request, 'core/vendor_form.html', {
        'form': form,
        'title': 'Add ISP vendor',
        'submit_label': 'Create vendor',
        'is_edit': False,
    })


@login_required(login_url='/login/')
def vendor_edit_view(request, pk):
    require_platform_superadmin(request)
    vendor = get_object_or_404(Vendor, pk=pk)
    if request.method == 'POST':
        form = VendorForm(request.POST, instance=vendor)
        if form.is_valid():
            vendor = form.save()
            messages.success(request, f'Vendor "{vendor.name}" updated.')
            return redirect('vendor_list')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = VendorForm(instance=vendor)
    return render(request, 'core/vendor_form.html', {
        'form': form,
        'vendor': vendor,
        'title': f'Edit vendor — {vendor.name}',
        'submit_label': 'Save changes',
        'is_edit': True,
    })