"""The two buttons on a connection row: test it now, or email the client's Admins a connect link."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.connections.admin import log, test_and_store
from apps.connections.emails import send_connect_request
from apps.connections.models import Connection, Status


def _connection(request, client_id, connection_id) -> Connection:
    if not request.user.has_perm('connections.change_connection'):
        raise PermissionDenied
    return get_object_or_404(Connection, pk=connection_id, client_id=client_id)


def _back(client_id):
    return redirect(reverse('admin:clients_client_change', args=[client_id]) + '#connections')


@require_POST
def test_connection(request, client_id, connection_id):
    connection = _connection(request, client_id, connection_id)
    messages.info(request, f'{connection.tool.name}: {test_and_store(connection)}')
    log(request, 'connection_tested', connection)
    return _back(client_id)


@require_POST
def send_connect_link(request, client_id, connection_id):
    connection = _connection(request, client_id, connection_id)
    if connection.tool.auth != 'oauth':
        messages.warning(request, f'{connection.tool.name} uses a key, not a connect link.')
        return _back(client_id)
    sent_to = send_connect_request(connection)
    if not sent_to:
        messages.warning(request, f'{connection.client} has no active Admin to send the link to. Add a client user first.')
        return _back(client_id)
    connection.status = Status.WAITING
    connection.save(update_fields=['status'])
    log(request, 'connect_link_sent', connection)
    messages.info(request, f'{connection.tool.name}: connect link sent to {", ".join(sent_to)}.')
    return _back(client_id)
