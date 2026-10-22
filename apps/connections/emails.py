"""Email asking the client's Admins to approve a 'Sign in with…' tool."""
from django.conf import settings

from apps.accounts.mailer import send
from apps.accounts.models import ClientUser, Role
from apps.connections.models import Connection


def send_connect_request(connection: Connection) -> list[str]:
    admins = list(ClientUser.objects.filter(client=connection.client, role=Role.ADMIN, is_active=True).values_list('email', flat=True))
    if admins:
        send(admins, f'Connect {connection.tool.name} to CiV', name=f'{connection.client.name} team', heading=f'Connect {connection.tool.name}',
             lines=[f'CiV is ready to read {connection.tool.name} for {connection.client.name} (read-only).',
                    'Sign in to the portal and open Source Registry to approve the connection.'],
             button='Open Source Registry', link=f'{settings.PORTAL_URL}/sources', note='CiV never changes anything in your tools.')
    return admins
