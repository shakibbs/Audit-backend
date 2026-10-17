"""Client API: Contact Ledger, a number's page, and "Can I call now?". A number typed by the client is turned into a
phone code with the client's key to find it, and never stored. Consent results are the strict ones (Module 6)."""
import re

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsClientUser
from apps.keyring.phones import normalize as clean_number
from apps.keyring.tokens import Tokenizer

from apps.consent.models import ConsentResult
from apps.consent.words import check_states, label_words, portal_status, proof_text, reason_text

from .calling import window
from .location import locate
from .models import ContactEvent, PhoneEpoch
from .normalize import mask

NOT_CHECKED = 'NOT_CHECKED'
LIMIT = 200
STATUSES = {'VERIFIED', 'WEAK', 'CONFLICTING', 'NO_PROOF', 'PENDING', 'NOT_NEEDED'}


def strict_results(contacts) -> dict:
    """The strict result of each contact (the one the portal shows), by contact ID."""
    return {r.contact_id: r for r in ConsentResult.objects.filter(contact__in=contacts, variant='strict').select_related('proof__certificate', 'contact')}


def number_ref(token: str) -> str:
    """The number's address in the portal: part of its phone code, never the number."""
    return f'p-{token[:24]}'


def where(c: ContactEvent) -> str:
    if c.is_non_us:
        return f'Outside the US ({c.country or "?"})'
    zones = c.time_zones or []
    zone = zones[0].split('/')[-1].replace('_', ' ') if len(zones) == 1 else f'{len(zones)} possible time zones' if zones else 'time zone unknown'
    return f'{c.recipient_state or c.country or "?"} · {zone}'


def flags(c: ContactEvent, copies: int, result=None) -> list[str]:
    out = label_words(result)
    if c.is_non_us:
        out.append('outside the US')
    if c.location_confidence == 'low':
        out.append('location unsure')
    if copies > 1:
        out.append(f'seen in {copies} tools')
    return out


def ledger_row(c: ContactEvent, copies: int, result=None) -> dict:
    return {'id': f'ce-{c.pk}', 'occurredAt': c.occurred_at, 'phoneDisplay': c.masked_label, 'phoneE164': number_ref(c.phone_token),
            'channel': c.get_channel_display(), 'category': 'Marketing' if c.direction == 'outbound' else 'Unknown',
            'bases': [b['basis'] for b in (result.bases if result else [])], 'status': portal_status(result),
            'code': (result.primary_code or '—') if result else '—', 'reasonText': reason_text(result), 'checks': check_states(result),
            'proof': proof_text(result), 'tiers': [], 'flags': flags(c, copies, result), 'hash': None,
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
        rows = ContactEvent.objects.filter(client=client, is_primary=True)
        if status == NOT_CHECKED:
            rows = rows.exclude(consent_results__variant='strict')
        elif status in STATUSES:
            rows = rows.filter(consent_results__variant='strict', consent_results__status=status.lower())
        elif status != 'ALL':
            return Response([])
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
        results = strict_results(rows)
        return Response([ledger_row(c, copies.get(c.dedupe_group, 1), results.get(c.pk)) for c in rows])


def seal_of(client, contacts) -> dict:
    """The nightly seal over this number's records: sealed when every record's fingerprint is in a sealed day."""
    from apps.ledger.models import Fingerprint
    prints = Fingerprint.objects.filter(client=client, source_record_id__in=[c.source_record_id for c in contacts]).select_related('anchor')
    sealed = [fp for fp in prints if fp.anchor_id]
    latest = max(sealed, key=lambda fp: fp.anchor.day).anchor if sealed else None
    return {'date': latest.day.isoformat() if latest else '', 'root': latest.root if latest else '',
            'anchored': bool(prints) and len(sealed) == len(prints), 'sealedCount': len(sealed), 'recordCount': len(prints),
            'stamped': bool(latest and latest.tsa_response)}


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
        results = strict_results(contacts)
        counted = [results.get(c.pk) for c in contacts if c.is_primary]
        counts: dict[str, int] = {}
        for r in counted:
            counts[portal_status(r)] = counts.get(portal_status(r), 0) + 1
        from apps.consent.panel import consent_panel, optouts_of, worst_of
        return Response({
            'phone': last.masked_label,
            'epoch': f'Owner {current.number}' if current else 'Owner 1',
            'epochCertainty': 'known' if len(epochs) > 1 else 'unknown',
            'worstStatus': worst_of(counted), 'counts': counts,
            'contacts': [{'id': f'ce-{c.pk}', 'occurredAt': c.occurred_at, 'channel': c.get_channel_display(), 'dialMode': c.dial_mode or None,
                          'status': portal_status(results.get(c.pk)), 'code': (results[c.pk].primary_code or '—') if c.pk in results else '—',
                          'bases': [{'basis': b['basis'], 'status': b['status'].upper()} for b in (results[c.pk].bases if c.pk in results else [])],
                          'labels': [c.direction, *([f'owner {c.epoch.number}'] if c.epoch_id else []), *([] if c.is_primary else ['copy from another tool']),
                                     *label_words(results.get(c.pk))]}
                         for c in contacts],
            'proofElements': [], 'optOuts': optouts_of(client, last.phone_token), 'listChecks': [],
            'consent': consent_panel(client, last.phone_token, current, results.values()),
            'anchor': seal_of(client, contacts), 'onHold': False,
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
