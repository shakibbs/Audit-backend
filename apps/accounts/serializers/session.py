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
        'clientId': str(client.pk), 'clientName': client.name, 'vertical': client.industry,
        'engagementMode': 'counsel_directed' if client.counsel_directed else 'direct',
        'plan': client.get_plan_display(),
        **updated_at(client),
    }
