"""Who may call an endpoint: any signed-in client user, or only a client Admin."""
from rest_framework.permissions import BasePermission

from apps.accounts.models import ClientUser


class IsClientUser(BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.user, ClientUser)


class IsClientAdmin(IsClientUser):
    message = 'Only an Admin can do this.'

    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.is_admin
