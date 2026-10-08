"""DRF authentication for the client API. Reads only the client login, never a staff login."""
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, CSRFCheck

from apps.accounts.session import current_user


class ClientSessionAuthentication(BaseAuthentication):
    def authenticate(self, request):
        user = current_user(request._request)
        if user is None:
            return None
        self.enforce_csrf(request)
        return (user, None)

    # Makes DRF answer 401 (not signed in) instead of 403 when there is no login.
    def authenticate_header(self, request):
        return 'Session'

    def enforce_csrf(self, request):
        check = CSRFCheck(lambda req: None)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            raise exceptions.PermissionDenied(f'CSRF failed: {reason}')
