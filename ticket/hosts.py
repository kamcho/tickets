from django_hosts import patterns, host

host_patterns = patterns(
    '',
    host(r'www', 'core.urls_main', name='www'),
    host(r'tickets', 'core.urls_tickets', name='tickets'),
    host(r'', 'core.urls_main', name='default'),
)
