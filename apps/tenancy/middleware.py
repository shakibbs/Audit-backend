"""Opens the right rows for each request: CiV staff in the admin panel see every client; a signed-in client user
sees only its own company; an insurer or acquirer user sees only what companies shared with it. Anyone else sees no
client data at all."""
from apps.accounts.session import current_user

from .scope import all_clients, buyer, tenant


class TenantScopeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/civ-admin/') and getattr(request, 'user', None) is not None and request.user.is_authenticated:
            with all_clients():
                return self.get_response(request)
        if request.path.startswith('/api/') and (user := current_user(request)) is not None:
            with tenant(user.client_id):
                return self.get_response(request)
        if request.path.startswith('/api/'):
            from apps.buyers.session import current_buyer
            if (person := current_buyer(request)) is not None:  # Module 15: an insurer or acquirer user
                with buyer(person.org_id):
                    return self.get_response(request)
        return self.get_response(request)
