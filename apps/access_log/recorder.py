"""record(): the one way every module writes to the access log."""
import ipaddress

from apps.access_log.models import AccessEntry


def client_ip(request) -> str | None:
    """The visitor's address. Behind our own proxies (the portal and the web proxy, on a private network) it is the last
    X-Forwarded-For entry, the one the proxy in front added; a visitor's own X-Forwarded-For is never trusted."""
    if request is None:
        return None
    remote = request.META.get('REMOTE_ADDR')
    forwarded = [p.strip() for p in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if p.strip()]
    try:
        trusted = remote is not None and (ipaddress.ip_address(remote).is_private or ipaddress.ip_address(remote).is_loopback)
        if trusted and forwarded:
            return str(ipaddress.ip_address(forwarded[-1]))
    except ValueError:
        pass
    return remote


def record(action: str, *, request=None, actor_kind: str = AccessEntry.ActorKind.SYSTEM,
           actor_id: int | None = None, actor_label: str = '', client_id: int | None = None,
           object: str = '') -> AccessEntry:
    return AccessEntry.objects.create(
        action=action, actor_kind=actor_kind, actor_id=actor_id, actor_label=actor_label,
        client_id=client_id, object=object, ip_address=client_ip(request),
    )
