"""What the portal learns about the signed-in user and their company."""
from apps.accounts.models import ClientUser


def initials(name: str) -> str:
    return ''.join(part[0] for part in name.split()[:2]).upper()


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
    }
