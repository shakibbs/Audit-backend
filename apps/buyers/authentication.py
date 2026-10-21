"""DRF authentication and permission for buyers. Client endpoints keep IsClientUser, so a buyer reaches none of them."""
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, CSRFCheck
from rest_framework.permissions import BasePermission

from .models import BuyerUser
from .session import current_buyer


class BuyerSessionAuthentication(BaseAuthentication):
    def authenticate(self, request):
        user = current_buyer(request._request)
        if user is None:
            return None
        check = CSRFCheck(lambda req: None)
        check.process_request(request._request)
        reason = check.process_view(request._request, None, (), {})
        if reason:
            raise exceptions.PermissionDenied(f'CSRF failed: {reason}')
        return (user, None)

    def authenticate_header(self, request):
        return 'Session'


class IsBuyerUser(BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.user, BuyerUser)
