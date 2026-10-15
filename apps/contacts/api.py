"""Client API: Contact Ledger, a number's page, and "Can I call now?". A number typed by the client is turned into a
phone code with the client's key to find it, and never stored. Consent is not checked until Module 6: said so."""
import re

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsClientUser
from apps.keyring.phones import normalize as clean_number
from apps.keyring.tokens import Tokenizer

from .calling import window
from .location import locate
from .models import ContactEvent, PhoneEpoch
from .normalize import mask

NOT_CHECKED = 'NOT_CHECKED'
REASON = 'Consent not checked yet (comes with the consent engine).'
LIMIT = 200


def number_ref(token: str) -> str:
    """The number's address in the portal: part of its phone code, never the number."""
    return f'p-{token[:24]}'


def where(c: ContactEvent) -> str:
    if c.is_non_us:
        return f'Outside the US ({c.country or "?"})'
    zones = c.time_zones or []
    zone = zones[0].split('/')[-1].replace('_', ' ') if len(zones) == 1 else f'{len(zones)} possible time zones' if zones else 'time zone unknown'
    return f'{c.recipient_state or c.country or "?"} · {zone}'


def flags(c: ContactEvent, copies: int) -> list[str]:
    out = []
    if c.is_non_us:
        out.append('outside the US')
    if c.location_confidence == 'low':
        out.append('location unsure')
    if copies > 1:
        out.append(f'seen in {copies} tools')
    return out


def ledger_row(c: ContactEvent, copies: int) -> dict:
    return {'id': f'ce-{c.pk}', 'occurredAt': c.occurred_at, 'phoneDisplay': c.masked_label, 'phoneE164': number_ref(c.phone_token),
            'channel': c.get_channel_display(), 'category': 'Marketing', 'bases': [], 'status': NOT_CHECKED, 'code': c.disposition or '—',
            'reasonText': REASON, 'checks': [], 'proof': '', 'tiers': [], 'flags': flags(c, copies), 'hash': None,
            'direction': c.direction, 'where': where(c), 'result': c.disposition, 'tool': c.source_system}


def find_tokens(client, q: str) -> dict | None:
    """A typed number → filter on its phone code; 4 digits → the last 4; otherwise nothing to filter."""
    digits = re.sub(r'\D', '', q or '')
    if not digits:
        return None
    if len(digits) >= 10 and (number := clean_number(q)):
        return {'phone_token': Tokenizer(client).token(number)}
    return {'masked_label__endswith': digits[-4:]}


class ContactsView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        client = request.user.client
        status = request.query_params.get('status') or 'ALL'
        if status not in ('ALL', NOT_CHECKED):
            return Response([])  # nothing has a consent status before Module 6
        rows = ContactEvent.objects.filter(client=client, is_primary=True)
        if (match := find_tokens(client, request.query_params.get('q', ''))) is not None:
            rows = rows.filter(**match)
        for name in ('channel', 'direction'):
            if value := request.query_params.get(name):
                rows = rows.filter(**{name: value.lower()})
        rows = list(rows.order_by('-occurred_at')[:LIMIT])
        groups = [c.dedupe_group for c in rows if c.dedupe_group]
        copies = {}
        for g in ContactEvent.objects.filter(client=client, dedupe_group__in=groups).values_list('dedupe_group', flat=True):
            copies[g] = copies.get(g, 0) + 1
        return Response([ledger_row(c, copies.get(c.dedupe_group, 1)) for c in rows])


class NumberView(APIView):
    """A number's page (the portal's evidence file), by its portal address."""
    permission_classes = [IsClientUser]

    def get(self, request, ref):
        client = request.user.client
        prefix = ref.removeprefix('p-')
        if not ref.startswith('p-') or not re.fullmatch(r'[0-9a-f]{24}', prefix):
            return Response({'detail': 'No evidence file for this number.'}, status=404)
        contacts = list(ContactEvent.objects.filter(client=client, phone_token__startswith=prefix).order_by('occurred_at'))
        if not contacts:
            return Response({'detail': 'No evidence file for this number.'}, status=404)
        last = contacts[-1]
        epochs = list(PhoneEpoch.objects.filter(client=client, phone_token=last.phone_token).order_by('number'))
        current = epochs[-1] if epochs else None
        return Response({
            'phone': last.masked_label,
            'epoch': f'Owner {current.number}' if current else 'Owner 1',
            'epochCertainty': 'known' if len(epochs) > 1 else 'unknown',
            'worstStatus': NOT_CHECKED, 'counts': {NOT_CHECKED: len(contacts)},
            'contacts': [{'id': f'ce-{c.pk}', 'occurredAt': c.occurred_at, 'channel': c.get_channel_display(), 'dialMode': c.dial_mode or None,
                          'status': NOT_CHECKED, 'code': c.disposition or '—', 'bases': [],
                          'labels': [c.direction, *([f'owner {c.epoch.number}'] if c.epoch_id else []), *([] if c.is_primary else ['copy from another tool'])]}
                         for c in contacts],
            'proofElements': [], 'optOuts': [], 'listChecks': [],
            'anchor': {'date': '', 'root': '', 'anchored': False}, 'onHold': False,
            'where': where(last), 'locationConfidence': last.location_confidence,
            'callingWindow': window(last.recipient_state, last.time_zones, last.is_non_us),
            'epochs': [{'number': e.number, 'from': e.started_at, 'to': e.ended_at, 'reason': e.get_reason_display()} for e in epochs],
        })


class CanCallView(APIView):
    """POST {number}: where the person probably is and whether calling now is inside their hours. Not stored."""
    permission_classes = [IsClientUser]

    def post(self, request):
        number = clean_number(str(request.data.get('number', '')))
        if number is None:
            return Response({'detail': 'Enter a full phone number.'}, status=400)
        found = locate(number)
        return Response({'number': mask(number), 'state': found['recipient_state'], 'country': found['country'],
                         'timeZones': found['time_zones'], 'confidence': found['location_confidence'],
                         'checkedAt': timezone.now(), **window(found['recipient_state'], found['time_zones'], found['is_non_us'])})
