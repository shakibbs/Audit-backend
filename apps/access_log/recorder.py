"""record(): the one way every module writes to the access log."""
from apps.access_log.models import AccessEntry


def client_ip(request) -> str | None:
    return request.META.get('REMOTE_ADDR') if request is not None else None


def record(action: str, *, request=None, actor_kind: str = AccessEntry.ActorKind.SYSTEM,
           actor_id: int | None = None, actor_label: str = '', client_id: int | None = None,
           object: str = '') -> AccessEntry:
    return AccessEntry.objects.create(
        action=action, actor_kind=actor_kind, actor_id=actor_id, actor_label=actor_label,
        client_id=client_id, object=object, ip_address=client_ip(request),
    )
