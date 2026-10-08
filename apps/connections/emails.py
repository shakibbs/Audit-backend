"""Email asking the client's Admins to approve a 'Sign in with…' tool."""
from django.conf import settings
from django.core.mail import send_mail

from apps.accounts.models import ClientUser, Role
from apps.connections.models import Connection


def send_connect_request(connection: Connection) -> list[str]:
    admins = list(ClientUser.objects.filter(client=connection.client, role=Role.ADMIN, is_active=True).values_list('email', flat=True))
    if admins:
        send_mail(
            f'Connect {connection.tool.name} to CiV',
            f'CiV is ready to read {connection.tool.name} for {connection.client.name} (read-only).\n\n'
            f'Sign in to the portal and open Source Registry to approve the connection:\n{settings.PORTAL_URL}/sources\n\n'
            'CiV never changes anything in your tools.',
            None, admins,
        )
    return admins
