"""What the portal learns about the signed-in user and their company."""
from apps.accounts.models import ClientUser


def initials(name: str) -> str:
    return ''.join(part[0] for part in name.split()[:2]).upper()


def updated_at(client) -> dict:
    """The top bar's "Updated" time: the last time CiV read something new from the company's tools."""
    from django.db.models import Max

    from apps.sync.models import SyncCursor
    last = SyncCursor.objects.filter(client=client).aggregate(m=Max('last_event_at'))['m']
    return {'updatedAt': last.isoformat()} if last else {}


def session_data(user: ClientUser | None) -> dict:
    if user is None:
        return {'signedIn': False}
    client = user.client
    return {
        'signedIn': True,
        'userId': str(user.pk), 'name': user.name, 'initials': initials(user.name), 'email': user.email,
        'role': user.role, 'isCounsel': user.is_counsel,
        'view': user.view, 'orgKind': 'client', 'canSwitchView': True,  # each person's own view (owner, 2026-10-22)
        'clientId': str(client.pk), 'clientName': client.name, 'vertical': client.industry,
        'plan': client.get_plan_display(),
        **updated_at(client),
        'periods': periods_of(client),
    }


def periods_of(client) -> list[dict]:
    from apps.scoring.snapshots import periods
    return periods(client)
