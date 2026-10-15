"""The door for live notices: a tool calls /hooks/<connection id> when something changes.
The tool's own signature is checked by its adapter; anything unsigned or unknown is refused."""
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.connections.models import Connection, Status

from .connector import BadSignature, connector_for
from .engine import receive_live


@csrf_exempt  # tools cannot send a CSRF token; their signature proves who they are
@require_POST
def hook(request, connection_id: int):
    connection = Connection.objects.select_related('client').filter(pk=connection_id, status__in=[Status.CONNECTED, Status.STALE]).first()
    tool = connector_for(connection) if connection else None
    if tool is None or not connection.client.can_sync:
        return HttpResponse(status=404)
    try:
        records = tool.parse_event(request.body, dict(request.headers) | {'_url': request.build_absolute_uri()})
    except BadSignature:
        return HttpResponse(status=403)
    receive_live(connection, records)
    return HttpResponse(status=204)
