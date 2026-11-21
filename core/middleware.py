from core.tenancy import resolve_vendor


class VendorMiddleware:
    """Attach request.vendor for multi-ISP scoping."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.vendor = resolve_vendor(request)
        return self.get_response(request)