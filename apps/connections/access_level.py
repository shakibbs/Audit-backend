"""Data access level 0–4 from what a client has connected (engineering spec, data access levels).

Each level needs the one below it: 1 contact logs (dialer or texting), 2 + certificate account,
3 + lead feed copy, 4 + CRM.
"""
from apps.clients.models import Client
from apps.connections.models import Status
from apps.connections.providers import Kind

LADDER = [(1, {Kind.DIALER, Kind.SMS}), (2, {Kind.CERTIFICATES}), (3, {Kind.LEAD_FEED}), (4, {Kind.CRM})]
COUNTS = {Status.CONNECTED, Status.STALE}  # a stale connection still connected once; it shows as stale


def access_level(client: Client) -> int:
    connected = set(client.connections.filter(status__in=COUNTS).values_list('kind', flat=True))
    level = 0
    for step, kinds in LADDER:
        if not connected & kinds:
            break
        level = step
    return level


def refresh_access_level(client: Client) -> int:
    level = access_level(client)
    if client.access_level != level:
        client.access_level = level
        client.save(update_fields=['access_level'])
    return level
