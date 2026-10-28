"""Buttons on a client company's page: a password link for a person (Users tab), and Resend on an invitation."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.access_log.recorder import record
from apps.accounts.admin import send_password_link
from apps.accounts.models import ClientUser, Invite


@require_POST
def password_link(request, client_id, user_id):
    if not request.user.has_perm('accounts.change_clientuser'):
        raise PermissionDenied
    user = get_object_or_404(ClientUser, pk=user_id, client_id=client_id)
    if not user.is_active:  # an old page or a second tab: a clear message, never a "not found" page
        messages.error(request, f'{user.name or user.email} is turned off. Tick "Is active" and save first, then send the link.')
    else:
        send_password_link(request, user)
    return redirect(reverse('admin:clients_client_change', args=[client_id]) + '#users')


@require_POST
def resend_invite(request, client_id, invite_id):
    if not request.user.has_perm('accounts.change_clientuser'):
        raise PermissionDenied
    from apps.accounts.invites import resend
    invite = get_object_or_404(Invite, pk=invite_id, client_id=client_id)
    try:
        resend(invite)
    except ValueError as error:
        messages.error(request, str(error))
    else:
        record('invite_resent', request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
               client_id=client_id, object=invite.email)
        messages.info(request, f'A new invitation link was sent to {invite.email}.')
    return redirect(reverse('admin:clients_client_change', args=[client_id]) + '#invites')
