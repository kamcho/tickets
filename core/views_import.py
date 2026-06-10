"""Bulk customer import from CSV — admin/receptionist only."""
import csv
import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect

from core.customer_accounts import (
    create_customer_user,
    default_customer_portal_password,
)
from core.phone_utils import normalize_kenya_phone, phone_match_key


def _user_can_import(user):
    return user.is_authenticated and user.role in ('Admin', 'Receptionist')


# Column name aliases accepted in the CSV header (case-insensitive)
_NAME_ALIASES    = {'name', 'full name', 'full_name', 'contact name', 'contact_name', 'fullname', 'customer name', 'customer_name'}
_PHONE_ALIASES   = {'phone', 'phone number', 'phone_number', 'mobile', 'mobile number', 'mobile_number', 'tel'}
_LOCATION_ALIASES = {'location', 'address', 'physical address', 'physical_address', 'map', 'google maps'}
_EMAIL_ALIASES   = {'email', 'email address', 'email_address', 'e-mail'}


def _find_col(header_row, aliases):
    """Return the actual column name from header_row that matches one of the aliases."""
    for col in header_row:
        if col.strip().lower() in aliases:
            return col
    return None


@login_required(login_url='/login/')
def customer_import_view(request):
    if not _user_can_import(request.user):
        messages.error(request, 'Only admins and receptionists can import customers.')
        return redirect('customer_list')

    if request.method != 'POST':
        return render(request, 'core/customer_import.html')

    csv_file = request.FILES.get('csv_file')
    if not csv_file:
        messages.error(request, 'Please select a CSV file to upload.')
        return render(request, 'core/customer_import.html')

    if not csv_file.name.lower().endswith('.csv'):
        messages.error(request, 'File must be a .csv file.')
        return render(request, 'core/customer_import.html')

    try:
        raw = csv_file.read().decode('utf-8-sig')  # utf-8-sig strips BOM
    except UnicodeDecodeError:
        try:
            csv_file.seek(0)
            raw = csv_file.read().decode('latin-1')
        except Exception:
            messages.error(request, 'Could not decode the file. Save it as UTF-8 CSV and try again.')
            return render(request, 'core/customer_import.html')

    reader = csv.DictReader(io.StringIO(raw))
    header = reader.fieldnames or []

    col_name     = _find_col(header, _NAME_ALIASES)
    col_phone    = _find_col(header, _PHONE_ALIASES)
    col_location = _find_col(header, _LOCATION_ALIASES)
    col_email    = _find_col(header, _EMAIL_ALIASES)

    if not col_name or not col_phone:
        missing = []
        if not col_name:
            missing.append('name (full name / contact name)')
        if not col_phone:
            missing.append('phone (mobile / tel)')
        messages.error(
            request,
            f'Required columns not found: {", ".join(missing)}. '
            f'Columns detected: {", ".join(header) or "(none)"}',
        )
        return render(request, 'core/customer_import.html')

    created_rows = []
    skipped_rows = []
    error_rows   = []

    from django.contrib.auth import get_user_model
    User = get_user_model()

    for row_num, row in enumerate(reader, start=2):
        name  = (row.get(col_name) or '').strip()
        phone = (row.get(col_phone) or '').strip()
        location = (row.get(col_location) or '').strip() if col_location else ''
        email    = (row.get(col_email) or '').strip() if col_email else ''

        if not name or not phone:
            error_rows.append({
                'row': row_num,
                'name': name or '—',
                'phone': phone or '—',
                'reason': 'Missing name or phone — row skipped.',
            })
            continue

        normalized = normalize_kenya_phone(phone)
        if not normalized:
            error_rows.append({
                'row': row_num,
                'name': name,
                'phone': phone,
                'reason': f'Invalid phone number "{phone}" — could not normalize to 254XXXXXXXXX.',
            })
            continue

        # Skip if a customer with this phone already exists
        key = phone_match_key(normalized)
        existing = None
        for u in User.objects.filter(role='Customer'):
            if phone_match_key(u.phone) == key:
                existing = u
                break

        if existing:
            skipped_rows.append({
                'row': row_num,
                'name': name,
                'phone': normalized,
                'reason': f'Customer already exists (account: {existing.display_name}).',
            })
            continue

        try:
            user = create_customer_user(
                contact_name=name,
                phone=normalized,
                password=default_customer_portal_password(normalized),
                email=email,
                location=location,
            )
            created_rows.append({
                'row': row_num,
                'name': user.display_name,
                'phone': user.phone,
            })
        except Exception as exc:
            error_rows.append({
                'row': row_num,
                'name': name,
                'phone': normalized,
                'reason': str(exc),
            })

    processed = len(created_rows) + len(skipped_rows) + len(error_rows)
    return render(request, 'core/customer_import.html', {
        'done': True,
        'created': created_rows,
        'skipped': skipped_rows,
        'errors': error_rows,
        'total_rows': processed,
    })
