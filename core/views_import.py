"""Bulk customer import from CSV — admin/receptionist only."""
import csv
import io
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from core.customer_accounts import (
    create_customer_user,
    default_customer_portal_password,
)
from core.phone_utils import normalize_kenya_phone, phone_match_key


def _require_import_permission(user):
    if not user.is_authenticated or user.role not in ('Admin', 'Receptionist'):
        raise PermissionDenied


# Column name aliases accepted in the CSV header (case-insensitive)
_NAME_ALIASES     = {'name', 'full name', 'full_name', 'contact name', 'contact_name', 'fullname', 'customer name', 'customer_name'}
_PHONE_ALIASES    = {'phone', 'phone number', 'phone_number', 'mobile', 'mobile number', 'mobile_number', 'tel'}
_LOCATION_ALIASES = {'location', 'address', 'physical address', 'physical_address', 'map', 'google maps'}
_EMAIL_ALIASES    = {'email', 'email address', 'email_address', 'e-mail'}


def _find_col(header_row, aliases):
    for col in header_row:
        if col.strip().lower() in aliases:
            return col
    return None


def _sse(event_type, **payload):
    """Format a single Server-Sent Event line."""
    payload['type'] = event_type
    return f"data: {json.dumps(payload)}\n\n"


def _decode_csv(csv_file):
    try:
        return csv_file.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        csv_file.seek(0)
        return csv_file.read().decode('latin-1')


def _stream_import(raw_csv, col_name, col_phone, col_location, col_email, total_rows):
    """Generator that yields SSE events while processing the CSV."""
    User = get_user_model()

    reader = csv.DictReader(io.StringIO(raw_csv))
    created = skipped = errors = 0

    # Pre-load all customer phones for fast duplicate detection
    existing_keys = {
        phone_match_key(u.phone)
        for u in User.objects.filter(role='Customer')
        if u.phone
    }

    for row_num, row in enumerate(reader, start=2):
        name     = (row.get(col_name) or '').strip()
        phone    = (row.get(col_phone) or '').strip()
        location = (row.get(col_location) or '').strip() if col_location else ''
        email    = (row.get(col_email) or '').strip() if col_email else ''

        processed = row_num - 1
        progress  = round(processed / total_rows * 100) if total_rows else 100

        # --- Validation ---
        if not name or not phone:
            errors += 1
            yield _sse('row', status='error', row=row_num, name=name or '—',
                       phone=phone or '—', progress=progress,
                       reason='Missing name or phone — row skipped.')
            continue

        if not email:
            errors += 1
            yield _sse('row', status='error', row=row_num, name=name,
                       phone=phone, progress=progress,
                       reason='No email address — row skipped.')
            continue

        normalized = normalize_kenya_phone(phone)
        if not normalized:
            errors += 1
            yield _sse('row', status='error', row=row_num, name=name,
                       phone=phone, progress=progress,
                       reason=f'Invalid phone "{phone}" — could not normalize to 254XXXXXXXXX.')
            continue

        key = phone_match_key(normalized)
        if key in existing_keys:
            skipped += 1
            yield _sse('row', status='skipped', row=row_num, name=name,
                       phone=normalized, progress=progress,
                       reason='Phone already exists — customer not duplicated.')
            continue

        try:
            user = create_customer_user(
                contact_name=name,
                phone=normalized,
                password=default_customer_portal_password(normalized),
                email=email,
                location=location,
            )
            existing_keys.add(key)
            created += 1
            yield _sse('row', status='created', row=row_num, name=user.display_name,
                       phone=user.phone, progress=progress, reason='')
        except Exception as exc:
            errors += 1
            yield _sse('row', status='error', row=row_num, name=name,
                       phone=normalized, progress=progress, reason=str(exc))

    yield _sse('done', created=created, skipped=skipped, errors=errors, total=total_rows)


@login_required(login_url='/login/')
def customer_import_view(request):
    _require_import_permission(request.user)

    if request.method != 'POST':
        return render(request, 'core/customer_import.html')

    csv_file = request.FILES.get('csv_file')
    if not csv_file or not csv_file.name.lower().endswith('.csv'):
        return render(request, 'core/customer_import.html', {
            'upload_error': 'Please upload a valid .csv file.',
        })

    try:
        raw = _decode_csv(csv_file)
    except Exception:
        return render(request, 'core/customer_import.html', {
            'upload_error': 'Could not read the file. Save it as UTF-8 CSV and try again.',
        })

    # Parse header to detect columns
    reader = csv.DictReader(io.StringIO(raw))
    header = reader.fieldnames or []

    col_name     = _find_col(header, _NAME_ALIASES)
    col_phone    = _find_col(header, _PHONE_ALIASES)
    col_location = _find_col(header, _LOCATION_ALIASES)
    col_email    = _find_col(header, _EMAIL_ALIASES)

    missing = []
    if not col_name:
        missing.append('name / full name / contact name')
    if not col_phone:
        missing.append('phone / mobile / tel')
    if not col_email:
        missing.append('email')
    if missing:
        return render(request, 'core/customer_import.html', {
            'upload_error': (
                f'Required column(s) not found: {", ".join(missing)}. '
                f'Columns detected: {", ".join(header) or "(none)"}.'
            ),
        })

    # Count data rows for progress bar
    total_rows = sum(1 for _ in csv.DictReader(io.StringIO(raw)))

    response = StreamingHttpResponse(
        _stream_import(raw, col_name, col_phone, col_location, col_email, total_rows),
        content_type='text/event-stream',
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'  # disable nginx buffering
    return response
