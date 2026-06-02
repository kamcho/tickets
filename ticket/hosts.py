from django.conf import settings
from django_hosts import patterns, host

# In development, bare localhost serves landing + portal routes (core.urls).
# In production, bare host serves the marketing site only (core.urls_main).
_default_urlconf = 'core.urls' if settings.DEBUG else 'core.urls_main'

host_patterns = patterns(
    '',
    host(r'www', 'core.urls_main', name='www'),
    host(r'tickets', 'core.urls_tickets', name='tickets'),
    host(r'', _default_urlconf, name='default'),
)
