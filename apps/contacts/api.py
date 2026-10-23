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
from .proof_elements import proof_elements
from .location import locate
from .models import ContactEvent, PhoneEpoch
from .normalize import mask
from apps.refs import number

NOT_CHECKED = 'NOT_CHECKED'
LIMIT = 200
STATUSES = {'VERIFIED', 'WEAK', 'CONFLICTING', 'NO_PROOF', 'PENDING', 'NOT_NEEDED'}


GRADE_TIER = {'A': 1, 'B': 2, 'C': 3, 'D': 4}  # source grade → the portal's evidence tier


def extras(client, contacts) -> dict:
    """Per contact: the category its consent need worked out, and its record's fingerprint (newest)."""
    from apps.consent.models import ConsentNeed
    from apps.ledger.models import Fingerprint
    ids = [c.pk for c in contacts]
    category = dict(ConsentNeed.objects.filter(contact_id__in=ids, variant='strict').values_list('contact_id', 'category'))
    prints = {}
    for system, record, sha in (Fingerprint.objects.filter(client=client, source_record_id__in=[c.source_record_id for c in contacts])
                                .order_by('fetched_at').values_list('source_system', 'source_record_id', 'sha256')):
        prints[(system, record)] = sha
    return {c.pk: (category.get(c.pk), prints.get((c.source_system, c.source_record_id))) for c in contacts}


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


def ledger_row(c: ContactEvent, copies: int, result=None, extra=(None, None)) -> dict:
    category, sha = extra
    return {'id': f'ce-{c.pk}', 'occurredAt': c.occurred_at, 'phoneDisplay': c.masked_label, 'phoneE164': number_ref(c.phone_token),
            'channel': c.get_channel_display(),
            'category': category.capitalize() if category else ('Marketing' if c.direction == 'outbound' else 'Unknown'),
            'bases': [b['basis'] for b in (result.bases if result else [])], 'status': portal_status(result),
            'code': (result.primary_code or '—') if result else '—', 'reasonText': reason_text(result), 'checks': check_states(result),
            'proof': proof_text(result), 'tiers': [GRADE_TIER[c.source_grade]] if c.source_grade in GRADE_TIER else [],
            'flags': flags(c, copies, result), 'hash': sha,
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
        results, more = strict_results(rows), extras(client, rows)
        return Response([ledger_row(c, copies.get(c.dedupe_group, 1), results.get(c.pk), more[c.pk]) for c in rows])


class ContactView(APIView):
    """One contact by its portal address (the contact panel opens any contact, not only the first 200 rows)."""
    permission_classes = [IsClientUser]

    def get(self, request, ref):
        client = request.user.client
        if not ref.startswith('ce-') or number(ref[3:]) is None:
            return Response({'detail': 'No such contact.'}, status=404)
        c = ContactEvent.objects.filter(client=client, pk=number(ref[3:])).first()
        if c is None:
            return Response({'detail': 'No such contact.'}, status=404)
        copies = ContactEvent.objects.filter(client=client, dedupe_group=c.dedupe_group).count() if c.dedupe_group else 1
        return Response(ledger_row(c, copies, strict_results([c]).get(c.pk), extras(client, [c])[c.pk]))


def seal_of(client, contacts) -> dict:
    """The nightly seal over this number's records: sealed when every record's fingerprint is in a sealed day."""
    from apps.ledger.models import Fingerprint
    prints = Fingerprint.objects.filter(client=client, source_record_id__in=[c.source_record_id for c in contacts]).select_related('anchor')
    sealed = [fp for fp in prints if fp.anchor_id]
    latest = max(sealed, key=lambda fp: fp.anchor.day).anchor if sealed else None
    return {'date': latest.day.isoformat() if latest else '', 'root': latest.root if latest else '',
            'anchored': bool(prints) and len(sealed) == len(prints), 'sealedCount': len(sealed), 'recordCount': len(prints),
            'stamped': bool(latest and latest.tsa_response)}


def came_from(client, token: str, epoch) -> str | None:
    """Where this owner's number came from (Module 8 provenance ladder), in words."""
    from apps.provenance.models import Provenance
    p = Provenance.objects.filter(client=client, phone_token=token, epoch=epoch).first()
    if p is None:
        return None
    name = f' · {p.source_name}' if p.source_name else ''
    own = ' (your own website)' if p.own_website else ''
    return f'{p.get_basis_display()}{name}{own}' + (f' · {p.note}' if p.basis == 'untraced' and p.note else '')


def list_checks(client, token: str) -> list[dict]:
    """The internal do-not-contact list is CiV's STOP list (STOP texts, CRM do-not-call); DNC check records come from
    the Upload centre (not supplied yet)."""
    from apps.optouts.models import OptOutEvent
    from apps.uploads.models import DncCheck, InternalListEntry
    stop = OptOutEvent.objects.filter(client=client, phone_token=token).order_by('at').first()
    entry = InternalListEntry.objects.filter(client=client, phone_token=token).order_by('added_on').first()
    since = min([d for d in (stop.at.date() if stop else None, entry.added_on if entry else None) if d], default=None)
    check = DncCheck.objects.filter(client=client, phone_token=token).order_by('-checked_on').first()
    supplied = DncCheck.objects.filter(client=client).exists()
    return [{'list': 'Internal do-not-contact list', 'onList': since is not None,
             'label': f'on it since {since:%d %b %Y}' if since else 'your list and STOP replies'},
            {'list': 'DNC check records', 'onList': check.listed if check else None,
             'label': f'{check.list_name} · checked {check.checked_on:%d %b %Y}' if check
             else 'not in your DNC check records' if supplied else 'DNC check records not supplied'}]


class NumberView(APIView):
    """A number's page (the portal's evidence file), by its portal address."""
    permission_classes = [IsClientUser]

    def get(self, request, ref):
        found = number_file(request.user.client, ref)
        if found is None:
            return Response({'detail': 'No evidence file for this number.'}, status=404)
        return Response(found)


def contacts_of(client, ref: str) -> list[ContactEvent]:
    """The number's contacts, oldest first, from its portal address ('p-' + part of its phone code)."""
    prefix = ref.removeprefix('p-')
    if not ref.startswith('p-') or not re.fullmatch(r'[0-9a-f]{24}', prefix):
        return []
    return list(ContactEvent.objects.filter(client=client, phone_token__startswith=prefix).order_by('occurred_at'))


def held(client, token: str) -> bool:
    from apps.evidence.holds import number_held
    return number_held(client, token)  # Module 14: under an active legal hold


def number_file(client, ref: str) -> dict | None:
    """Everything the number page shows (also the base of the evidence file, Module 14)."""
    contacts = contacts_of(client, ref)
    if not contacts:
        return None
    last = contacts[-1]
    epochs = list(PhoneEpoch.objects.filter(client=client, phone_token=last.phone_token).order_by('number'))
    current = epochs[-1] if epochs else None
    results = strict_results(contacts)
    counted = [results.get(c.pk) for c in contacts if c.is_primary]
    counts: dict[str, int] = {}
    for r in counted:
        counts[portal_status(r)] = counts.get(portal_status(r), 0) + 1
    from apps.consent.panel import consent_panel, optouts_of, worst_of
    return {
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
        'proofElements': proof_elements(client, last.phone_token, current, contacts, results), 'optOuts': optouts_of(client, last.phone_token), 'listChecks': list_checks(client, last.phone_token),
        'consent': consent_panel(client, last.phone_token, current, results.values()),
        'cameFrom': came_from(client, last.phone_token, current),
        'anchor': seal_of(client, contacts), 'onHold': held(client, last.phone_token),
        'where': where(last), 'locationConfidence': last.location_confidence,
        'callingWindow': window(last.recipient_state, last.time_zones, last.is_non_us),
        'epochs': [{'number': e.number, 'from': e.started_at, 'to': e.ended_at, 'reason': e.get_reason_display()} for e in epochs],
    }


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
