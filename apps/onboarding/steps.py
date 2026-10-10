"""The onboarding steps, in order. "auto" steps tick themselves from the client's data; the rest a person ticks."""
from dataclasses import dataclass
from typing import Callable

from apps.accounts.models import ClientUser, Role
from apps.clients.models import Client
from apps.connections.models import Status
from apps.connections.providers import Kind


def _connected(kind: str) -> Callable[[Client], bool]:
    return lambda client: client.connections.filter(kind=kind, status=Status.CONNECTED).exists()


def _has_admin(client: Client) -> bool:
    return ClientUser.objects.filter(client=client, role=Role.ADMIN, is_active=True).exists()


@dataclass(frozen=True)
class Step:
    code: str
    label: str
    hint: str
    auto: Callable[[Client], bool] | None = None  # None = a person ticks it
    document_kind: str = ''  # if set, uploading this kind of document also marks the step done


STEPS = [
    Step('agreement', 'Agreement signed', 'The service agreement is signed. Uploading it on the Documents tab marks this done.',
         document_kind='agreement'),
    Step('annex_c', 'Annex C signed', 'Permission for CiV test opt-outs. Uploading it on the Documents tab marks this done.',
         document_kind='annex_c'),
    Step('campaigns', 'Campaigns marked', 'The client confirmed which campaigns are marketing and which are informational.'),
    Step('dialer', 'Dialer connected', 'Ticks itself when a dialer connection shows Connected.', _connected(Kind.DIALER)),
    Step('texting', 'Texting tool connected', 'Ticks itself when a texting connection shows Connected.', _connected(Kind.SMS)),
    Step('client_admin', 'Client Admin added', 'Ticks itself when the client has an active Admin user.', _has_admin),
    Step('first_sync', 'First sync done', 'The first full read of the client\'s tools finished. Ticked by hand until live sync exists.'),
]
STEP_CODES = {step.code for step in STEPS}
MANUAL_CODES = {step.code for step in STEPS if step.auto is None}
