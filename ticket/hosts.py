from django.conf import settings
from django_hosts import patterns, host

# In development (or temporary IP access), bare host serves landing + portal (core.urls).
# In normal production, bare host serves marketing only (core.urls_main); use tickets.* for portal.
_use_combined = settings.DEBUG or getattr(settings, 'SERVE_COMBINED_ON_DEFAULT_HOST', False)
_default_urlconf = 'core.urls' if _use_combined else 'core.urls_main'

host_patterns = patterns(
    '',
    host(r'www', 'core.urls_main', name='www'),
    host(r'tickets', 'core.urls_tickets', name='tickets'),
    host(r'', _default_urlconf, name='default'),
)
