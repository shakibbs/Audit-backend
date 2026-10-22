"""The login system's emails: password link and invitation (for a client's Admin added by CiV, or a person invited by
the client's Admin)."""
from django.conf import settings

from apps.accounts.mailer import send
from apps.accounts.models import ClientUser, Invite, Role


def send_reset(user: ClientUser, uid: str, token: str) -> None:
    send(user.email, 'Choose a new CiV password', name=user.name, heading='Choose a new password',
         lines=['Use the button below within 1 hour to choose a new password for the CiV portal.'],
         button='Choose a new password', link=f'{settings.PORTAL_URL}/sign-in?reset={uid}.{token}',
         note='If you did not ask for this, you can ignore this email; your password stays the same.')


def send_invite(invite: Invite, token: str) -> None:
    role = 'an Admin' if invite.role == Role.ADMIN else 'a Member'
    lawyer = " and the company's lawyer" if invite.is_counsel else ''
    send(invite.email, f'You are invited to the CiV portal for {invite.client.name}', name=invite.name or invite.email,
         heading=f'Welcome to CiV, {invite.client.name}',
         lines=[f'You have been invited to the CiV compliance portal for {invite.client.name}, as {role}{lawyer}.',
                'Click the button to choose your own password. The link works once, for 7 days.'],
         button='Choose your password', link=f'{settings.PORTAL_URL}/sign-in?invite={token}',
         note='Nobody at CiV will ever ask you for your password.')
