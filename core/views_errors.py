"""Custom error pages shown when DEBUG is False."""

from django.conf import settings
from django.shortcuts import render

from core.phone_utils import normalize_kenya_phone


def _contact_context():
    primary = getattr(settings, 'COMPANY_PHONE_PRIMARY', '0792929275')
    email = getattr(settings, 'COMPANY_EMAIL', 'metrolinkssolutionltd@gmail.com')
    primary_tel = normalize_kenya_phone(primary)
    return {
        'company_phone_primary': primary,
        'company_email': email,
        'company_phone_primary_tel': f'+{primary_tel}' if primary_tel else primary,
    }


def _error_context(code, title, message, hint=''):
    ctx = {
        'error_code': code,
        'error_title': title,
        'error_message': message,
        'error_hint': hint,
    }
    ctx.update(_contact_context())
    return ctx


def page_not_found(request, exception):
    return render(
        request,
        'core/errors/404.html',
        _error_context(
            '404',
            'Page not found',
            'The page you requested does not exist or may have been moved.',
            'Check the address, or use the links below to get back on track.',
        ),
        status=404,
    )


def server_error(request):
    return render(
        request,
        'core/errors/500.html',
        _error_context(
            '500',
            'Something went wrong',
            'We hit an unexpected problem while loading this page.',
            'Our team has been notified. Please try again in a few minutes.',
        ),
        status=500,
    )


def permission_denied(request, exception):
    return render(
        request,
        'core/errors/403.html',
        _error_context(
            '403',
            'Access denied',
            'You do not have permission to view this page.',
            'Sign in with the correct account, or contact your administrator.',
        ),
        status=403,
    )


def bad_request(request, exception):
    return render(
        request,
        'core/errors/400.html',
        _error_context(
            '400',
            'Bad request',
            'Your browser sent a request we could not process.',
            'Go back and try again. If the problem continues, clear your cookies and retry.',
        ),
        status=400,
    )
