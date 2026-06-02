from django.conf import settings


def portal_urls(request):
    """Client portal login URL: production absolute URL, or same host in development."""
    login_url = settings.TICKETS_PORTAL_LOGIN_URL
    if not login_url and request:
        login_url = request.build_absolute_uri('/login/')
    return {'client_portal_login_url': login_url}
