"""Client API: the Source Registry list and the Overview's Data health card, from the real connections and sync.
The upload rows keep the names the Upload centre offers; no upload is tracked here yet."""
from django.db.models import Max
from django.utils.timesince import timesince
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsClientUser
from apps.connections.models import Status
from apps.connections.providers import Kind

from .connector import CONNECTORS, connector_for
from .health import state
from .models import SyncCursor

# Files the client uploads on Source Registry (Upload centre). Shown as before; their uploads are tracked elsewhere.
UPLOAD_ROWS = [
    ('Internal do-not-contact list', None), ('Policies, training, contracts', None), ('Complaint log', None),
    ('DNC check records', 'Blocks M13'), ('Reassigned-number query logs', 'Blocks M11'),
]
TIER = {Kind.CERTIFICATES: 2}  # certificates come from an independent third party; the client's own tools are tier 3
STATE = {'live': 'current', 'catching_up': 'current', 'stale': 'stale', 'never': 'not_supplied'}
LEVEL_TEXT = {0: 'nothing connected yet', 1: 'dialer or texting connected', 2: 'plus a certificate account',
              3: 'plus a lead feed', 4: 'plus a CRM'}


def when(moment) -> str:
    return f'{timesince(moment)} ago' if moment else '—'


def tool_row(connection, cursor) -> dict:
    tool = connector_for(connection) if connection.provider in CONNECTORS else None
    every = max(2, getattr(tool, 'min_poll_minutes', 0) or 0)
    if tool is None:
        status, blocks, access = 'not_supplied', 'Not read yet: its connector comes when needed', 'Saved'
    elif connection.status not in (Status.CONNECTED, Status.STALE):
        status = 'not_supplied'
        blocks = 'Waiting for you to click Allow' if connection.tool.auth == 'oauth' else 'Not connected yet'
        access = 'Sign in with ' + connection.tool.name if connection.tool.auth == 'oauth' else 'API key'
    else:
        status = STATE[state(cursor)]
        blocks = 'No news for over 2 hours' if status == 'stale' else None
        access = f'Connected by API · read every {every} minutes'
    return {'id': f'conn-{connection.pk}', 'name': connection.tool.name + (f' ({connection.label})' if connection.label else ''),
            'tier': TIER.get(connection.kind, 3), 'access': access, 'lastSync': when(cursor.last_heartbeat_at if cursor else None),
            'status': status, 'feeds': [], 'revocable': True, 'acceptsUpload': False, 'blocks': blocks}


class SourcesView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        connections = request.user.client.connections.all()
        cursors = {c.connection_id: c for c in SyncCursor.objects.filter(connection__in=connections)}
        rows = [tool_row(c, cursors.get(c.pk)) for c in connections]
        rows += [{'id': f'upload-{i}', 'name': name, 'tier': 4, 'access': 'Upload', 'lastSync': '—', 'status': 'not_supplied',
                  'feeds': [], 'revocable': False, 'acceptsUpload': True, 'blocks': blocks} for i, (name, blocks) in enumerate(UPLOAD_ROWS, 1)]
        return Response(rows)


class DataHealthView(APIView):
    """Real: access level, tools live / stale / not connected, last change. Not measured yet: records completeness
    (Module 5) and conversation review (Module 9), sent as null."""
    permission_classes = [IsClientUser]

    def get(self, request):
        client = request.user.client
        connections = list(client.connections.all())
        cursors = {c.connection_id: c for c in SyncCursor.objects.filter(connection__in=connections)}
        rows = [tool_row(c, cursors.get(c.pk)) for c in connections]
        last = SyncCursor.objects.filter(client=client).aggregate(at=Max('last_event_at'))['at']
        return Response({
            'accessLevel': client.access_level,
            'accessLabel': f'Level {client.access_level} · {LEVEL_TEXT[client.access_level]}',
            'lastChangeAt': last,  # None until something has been read
            'sources': {'live': sum(r['status'] == 'current' for r in rows), 'stale': sum(r['status'] == 'stale' for r in rows),
                        'notSupplied': sum(r['status'] == 'not_supplied' for r in rows), 'total': len(rows)},
            **records_completeness(client), 'conversationReview': None,
        })


def records_completeness(client) -> dict:
    """The Overview's Records completeness box (M37, Module 5): the latest month checked, with a one-line reason."""
    from apps.reconcile.models import PeriodIntegrity, Reconciliation
    from apps.reconcile.summary import tool_name
    month = PeriodIntegrity.objects.filter(client=client).order_by('-period').first()
    if month is None:
        return {'recordsCompleteness': None, 'completenessFloor': 0.9, 'completenessStatus': 'not_measured', 'completenessNote': None}
    label = month.period.strftime('%B %Y')
    if month.completeness is None:
        return {'recordsCompleteness': None, 'completenessFloor': month.floor, 'completenessStatus': 'not_available',
                'completenessNote': f'No tool gave a bill or a total to compare with yet · {label}'}
    lowest = (Reconciliation.objects.filter(client=client, period=month.period, measure__in=['calls', 'texts', 'vendor_leads', 'crm_records'],
                                            available=True, ratio__isnull=False).order_by('ratio').first())
    if month.incomplete and lowest:
        tool = tool_name(lowest.source_system)
        against = {'bill': f'what {tool} billed', 'tool_total': f'what {tool} itself counted'}.get(lowest.method, f'the working days ({tool})')
        note = f'CiV received only {round(month.completeness * 100)}% of the {lowest.get_measure_display().lower()} compared with {against} · {label}'
    else:
        note = f"Every connected tool compared with its bill, its own count or its working days · {label}"
    return {'recordsCompleteness': month.completeness, 'completenessFloor': month.floor,
            'completenessStatus': 'incomplete' if month.incomplete else 'complete', 'completenessNote': note}
