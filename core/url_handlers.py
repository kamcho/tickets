"""Shared HTTP error handlers (wired into each host URLconf)."""

handler404 = 'core.views_errors.page_not_found'
handler500 = 'core.views_errors.server_error'
handler403 = 'core.views_errors.permission_denied'
handler400 = 'core.views_errors.bad_request'
