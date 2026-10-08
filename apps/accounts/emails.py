"""The two emails the login system sends: password reset and invite."""
from django.conf import settings
from django.core.mail import send_mail

from apps.accounts.models import ClientUser, Invite


def send_reset(user: ClientUser, uid: str, token: str) -> None:
    link = f'{settings.PORTAL_URL}/sign-in?reset={uid}.{token}'
    send_mail(
        'Choose a new CiV password',
        f'Hello {user.name},\n\nUse this link within 1 hour to choose a new password:\n{link}\n\n'
        'If you did not ask for this, you can ignore this email.',
        None, [user.email],
    )


def send_invite(invite: Invite, token: str) -> None:
    link = f'{settings.PORTAL_URL}/sign-in?invite={token}'
    send_mail(
        f'You are invited to the CiV portal for {invite.client.name}',
        f'Hello {invite.name},\n\nYou have been invited to the CiV portal for {invite.client.name}.\n'
        f'Use this link within 7 days to choose your password:\n{link}',
        None, [invite.email],
    )
