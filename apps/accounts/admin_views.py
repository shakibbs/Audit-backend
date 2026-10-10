"""Button on a person in a client company's Users tab: email them a link to set their password."""
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.admin import send_password_link
from apps.accounts.models import ClientUser


@require_POST
def password_link(request, client_id, user_id):
    if not request.user.has_perm('accounts.change_clientuser'):
        raise PermissionDenied
    user = get_object_or_404(ClientUser, pk=user_id, client_id=client_id, is_active=True)
    send_password_link(request, user)
    return redirect(reverse('admin:clients_client_change', args=[client_id]) + '#users')
