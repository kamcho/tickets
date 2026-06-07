"""Template context for portal URLs, permissions, and company contact."""

from django.conf import settings



from core.customer_accounts import get_customer_user

from core.phone_utils import normalize_kenya_phone





def portal_urls(request):

    """Client portal and staff agent login URLs (absolute in production when configured)."""

    client_login = settings.TICKETS_PORTAL_LOGIN_URL
    staff_login = ''

    if request:
        try:
            if not client_login:
                client_login = request.build_absolute_uri('/portal/login/')
            staff_login = request.build_absolute_uri('/login/')
        except Exception:
            if not client_login:
                client_login = '/portal/login/'
            staff_login = '/login/'

    elif not client_login and not getattr(settings, 'DEBUG', True):
        client_login = 'https://tickets.metrolinkssolutionltd.co.ke/portal/login/'

    if not staff_login and not getattr(settings, 'DEBUG', True):
        staff_login = 'https://tickets.metrolinkssolutionltd.co.ke/login/'

    return {
        'client_portal_login_url': client_login or '/portal/login/',
        'staff_login_url': staff_login or '/login/',
    }





def portal_customer(request):

    """Current customer profile for portal templates."""

    user = getattr(request, 'user', None)

    return {'customer': get_customer_user(user)}





def staff_permissions(request):

    """Staff UI flags (e.g. hide create-ticket for field agents)."""

    user = getattr(request, 'user', None)

    can_create = (

        user is not None

        and user.is_authenticated

        and getattr(user, 'role', None) in ('Admin', 'Receptionist')

    )

    return {'can_create_ticket': can_create}





def company_contact(request):

    """Office phones, email, and WhatsApp link for footer / floating button."""

    primary = getattr(settings, 'COMPANY_PHONE_PRIMARY', '0792929275')

    secondary = getattr(settings, 'COMPANY_PHONE_SECONDARY', '0746464696')

    email = getattr(settings, 'COMPANY_EMAIL', 'metrolinkssolutionltd@gmail.com')



    wa_digits = (

        getattr(settings, 'WHATSAPP_DISPLAY_NUMBER', '').strip()

        or normalize_kenya_phone(primary)

    )

    wa_url = f'https://wa.me/{wa_digits}' if wa_digits else ''



    primary_tel = normalize_kenya_phone(primary)

    secondary_tel = normalize_kenya_phone(secondary)



    return {

        'company_phone_primary': primary,

        'company_phone_secondary': secondary,

        'company_email': email,

        'company_phone_primary_tel': f'+{primary_tel}' if primary_tel else primary,

        'company_phone_secondary_tel': f'+{secondary_tel}' if secondary_tel else secondary,

        'company_whatsapp_digits': wa_digits,

        'company_whatsapp_url': wa_url,

    }


