"""Phone codes: phone number + the client's secret key → phone_token (HMAC-SHA256). The number itself is never saved."""
import base64
import hashlib
import hmac
import secrets

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.access_log.recorder import record
from apps.connections.crypto import lock, unlock
from apps.tenancy.scope import tenant

from .models import ClientKey
from .phones import normalize


class KeyDestroyed(Exception):
    """The client's key was destroyed (contract ended): no more codes can be made for it."""


def active_key(client) -> ClientKey:
    """The client's key in use; made on first need. Never makes a new one after a key was destroyed."""
    with tenant(client):
        return _active_key(client)


def _active_key(client) -> ClientKey:
    key = ClientKey.objects.filter(client=client, destroyed_at__isnull=True).first()
    if key:
        return key
    if ClientKey.objects.filter(client=client).exists():
        raise KeyDestroyed(f'The phone-code key for client {client.pk} was destroyed.')
    try:
        with transaction.atomic():
            key = ClientKey.objects.create(client=client, kid='k1', locked_key=lock({'k': base64.b64encode(secrets.token_bytes(32)).decode()}))
    except IntegrityError:  # another job made it at the same moment
        return ClientKey.objects.get(client=client, destroyed_at__isnull=True)
    record('client_key_created', client_id=client.pk, object=key.kid)
    return key


class Tokenizer:
    """Opens the client's key once, then codes many numbers. Used inside a job; the key never leaves memory."""

    def __init__(self, client):
        key = active_key(client)
        self.kid = key.kid
        self._secret = base64.b64decode(unlock(key.locked_key)['k'])

    def token(self, raw_phone: str) -> str | None:
        e164 = normalize(raw_phone)
        if e164 is None:
            return None
        return hmac.new(self._secret, e164.encode(), hashlib.sha256).hexdigest()


def destroy_key(client, *, actor_kind: str = 'system', actor_id: int | None = None, actor_label: str = '') -> None:
    """Contract end: wipe the client's key. Every code already saved can no longer be linked to a number."""
    with tenant(client), transaction.atomic():
        for key in ClientKey.objects.select_for_update().filter(client=client, destroyed_at__isnull=True):
            key.locked_key = ''
            key.destroyed_at = timezone.now()
            key.save(update_fields=['locked_key', 'destroyed_at'])
            record('client_key_destroyed', client_id=client.pk, object=key.kid,
                   actor_kind=actor_kind, actor_id=actor_id, actor_label=actor_label)
