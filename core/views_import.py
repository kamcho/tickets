"""Bulk customer import from CSV — admin/receptionist only."""
import csv
import io
import traceback

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from core.customer_accounts import (
    _email_from_phone,
    default_customer_portal_password,
    split_contact_name,
)
from core.phone_utils import normalize_kenya_phone, phone_match_key, digits_only


def _require_import_permission(user):
    if not user.is_authenticated or user.role not in ('Admin', 'Receptionist'):
        raise PermissionDenied


def _log(msg):
    print(f"[CSV IMPORT] {msg}", flush=True)


# Column name aliases (case-insensitive)
_NAME_ALIASES     = {'name', 'full name', 'full_name', 'contact name', 'contact_name',
                     'fullname', 'customer name', 'customer_name'}
_PHONE_ALIASES    = {'phone', 'phone number', 'phone_number', 'mobile',
                     'mobile number', 'mobile_number', 'tel'}
_LOCATION_ALIASES = {'location', 'address', 'physical address', 'physical_address',
                     'map', 'google maps'}
_EMAIL_ALIASES    = {'email', 'email address', 'email_address', 'e-mail'}

# Values that look like "no email" — treat as missing
_JUNK_EMAILS = {
    '', 'n/a', 'na', 'none', 'null', 'nil', '-', '--', 'noemail',
    'no email', 'not available', 'not provided',
}


def _find_col(header_row, aliases):
    for col in header_row:
        if col.strip().lower() in aliases:
            return col
    return None


def _clean_email(raw_email):
    """Return a usable email or None if the value is junk/missing."""
    v = (raw_email or '').strip().lower()
    if v in _JUNK_EMAILS:
        return None
    if '@' not in v:
        return None
    return raw_email.strip()


def _decode_csv(csv_file):
    try:
        return csv_file.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        csv_file.seek(0)
        return csv_file.read().decode('latin-1')


def _bulk_create_customer(User, name, phone_normalized, email, location, password):
    """
    Fast direct create — no full-table phone scan.
    Caller has already verified the phone doesn't exist.
    Falls back to phone-derived email if email is taken by another customer.
    """
    first_name, last_name = split_contact_name(name)

    # Resolve email: use provided if free, otherwise derive from phone
    derived_email = _email_from_phone(phone_normalized)
    if email:
        norm_email = User.objects.normalize_email(email)
        # Skip provided email if taken by staff or another customer
        if User.objects.filter(email__iexact=norm_email).exists():
            _log(f"  email {norm_email!r} already taken — using derived email")
            email_to_use = derived_email
        else:
            email_to_use = norm_email
    else:
        email_to_use = derived_email

    user = User.objects.create_user(
        email=email_to_use,
        password=password,
        first_name=first_name,
        last_name=last_name or '-',
        phone=phone_normalized,
        role='Customer',
        location=location or '',
        is_staff=False,
        is_active=True,
    )
    return user


@login_required(login_url='/login/')
def customer_import_view(request):
    _require_import_permission(request.user)
    _log(f"method={request.method} user={request.user}")

    if request.method != 'POST':
        return render(request, 'core/customer_import.html')

    csv_file = request.FILES.get('csv_file')
    _log(f"file={csv_file.name if csv_file else 'None'}")

    if not csv_file or not csv_file.name.lower().endswith('.csv'):
        return render(request, 'core/customer_import.html', {
            'upload_error': 'Please upload a valid .csv file.',
        })

    try:
        raw = _decode_csv(csv_file)
        _log(f"decoded {len(raw)} chars")
    except Exception as e:
        _log(f"decode error: {e}\n{traceback.format_exc()}")
        return render(request, 'core/customer_import.html', {
            'upload_error': 'Could not read the file. Save it as UTF-8 CSV and try again.',
        })

    reader = csv.DictReader(io.StringIO(raw))
    header = reader.fieldnames or []
    _log(f"headers: {header}")

    col_name     = _find_col(header, _NAME_ALIASES)
    col_phone    = _find_col(header, _PHONE_ALIASES)
    col_location = _find_col(header, _LOCATION_ALIASES)
    col_email    = _find_col(header, _EMAIL_ALIASES)
    _log(f"cols: name={col_name!r} phone={col_phone!r} location={col_location!r} email={col_email!r}")

    if not col_name or not col_phone:
        missing = []
        if not col_name:
            missing.append('name / full name / contact name')
        if not col_phone:
            missing.append('phone / mobile / tel')
        _log(f"missing required cols: {missing}")
        return render(request, 'core/customer_import.html', {
            'upload_error': (
                f'Required column(s) not found: {", ".join(missing)}. '
                f'Columns detected: {", ".join(header) or "(none)"}.'
            ),
        })

    User = get_user_model()

    # --- Pre-load all existing customer phone keys into a set (ONE query) ---
    _log("loading existing customer phones…")
    existing_keys = {
        phone_match_key(u.phone)
        for u in User.objects.filter(role='Customer').only('phone')
        if u.phone
    }
    _log(f"loaded {len(existing_keys)} existing phone keys")

    log_rows = []

    for row_num, row in enumerate(reader, start=2):
        name     = (row.get(col_name) or '').strip()
        raw_phone = (row.get(col_phone) or '').strip()
        location = (row.get(col_location) or '').strip() if col_location else ''
        raw_email = (row.get(col_email) or '').strip() if col_email else ''

        _log(f"row {row_num}: name={name!r} phone={raw_phone!r} email={raw_email!r}")

        if not name or not raw_phone:
            _log(f"  → skip: missing name/phone")
            log_rows.append({'row': row_num, 'status': 'error',
                             'name': name or '—', 'phone': raw_phone or '—',
                             'reason': 'Missing name or phone — row skipped.'})
            continue

        normalized = normalize_kenya_phone(raw_phone)
        if not normalized:
            _log(f"  → skip: bad phone {raw_phone!r}")
            log_rows.append({'row': row_num, 'status': 'error',
                             'name': name, 'phone': raw_phone,
                             'reason': f'Invalid phone "{raw_phone}" — could not normalize to 254XXXXXXXXX.'})
            continue

        key = phone_match_key(normalized)
        if key in existing_keys:
            _log(f"  → skip: duplicate phone key {key!r}")
            log_rows.append({'row': row_num, 'status': 'skipped',
                             'name': name, 'phone': normalized,
                             'reason': 'Phone already exists — customer not duplicated.'})
            continue

        email = _clean_email(raw_email)  # None if junk/missing

        password = default_customer_portal_password(normalized)

        try:
            user = _bulk_create_customer(User, name, normalized, email, location, password)
            existing_keys.add(key)  # prevent within-file duplicates
            _log(f"  → created: {user.display_name} ({user.phone})")
            log_rows.append({'row': row_num, 'status': 'created',
                             'name': user.display_name, 'phone': user.phone,
                             'reason': ''})
        except Exception as exc:
            _log(f"  → error: {exc}\n{traceback.format_exc()}")
            log_rows.append({'row': row_num, 'status': 'error',
                             'name': name, 'phone': normalized,
                             'reason': str(exc)})

    summary = {
        'created': sum(1 for r in log_rows if r['status'] == 'created'),
        'skipped': sum(1 for r in log_rows if r['status'] == 'skipped'),
        'errors':  sum(1 for r in log_rows if r['status'] == 'error'),
        'total':   len(log_rows),
    }
    _log(f"done — created={summary['created']} skipped={summary['skipped']} errors={summary['errors']}")

    return render(request, 'core/customer_import.html', {
        'done': True,
        'log_rows': log_rows,
        'summary': summary,
    })
