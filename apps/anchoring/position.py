"""The Vault's position lookup: what CiV held about one number on one day (as of the end of that day), and the hash
check: is this fingerprint one CiV recorded, and in which day's seal. The number is typed by the client, turned into a
phone code with its key, and never stored."""
from datetime import UTC, date, datetime, time, timedelta

from apps.captures.models import PageCapture
from apps.consent.models import ConsentProof, ConsentResult
from apps.contacts.models import ContactEvent, PhoneEpoch
from apps.contacts.normalize import mask
from apps.keyring.phones import normalize
from apps.keyring.tokens import Tokenizer
from apps.ledger.models import Fingerprint
from apps.optouts.models import OptOutEvent
from apps.provenance.models import Provenance
from apps.uploads.models import InternalListEntry

GRADE_TIER = {'A': 1, 'B': 2, 'C': 3, 'D': 4}


def row(label, value, source):
    return {'label': label, 'value': value, 'source': source}


def position(client, typed: str, day: date) -> dict | None:
    number = normalize(typed)
    if number is None:
        return None
    token = Tokenizer(client).token(number)
    end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=UTC)
    rows = []
    moment = end - timedelta(microseconds=1)  # the end of that day
    epoch = next((e for e in PhoneEpoch.objects.filter(client=client, phone_token=token).order_by('number')
                  if (e.started_at is None or e.started_at <= moment) and (e.ended_at is None or moment < e.ended_at)), None)
    if epoch:
        since = f' · since {epoch.started_at:%b %Y}' if epoch.started_at else ''
        rows.append(row('Phone epoch', f'Owner {epoch.number}{since}', epoch.get_reason_display()))
    proof = (ConsentProof.objects.filter(client=client, phone_token=token, captured_at__lt=end, **({'epoch': epoch} if epoch else {}))
             .filter(created_at__lt=end).select_related('certificate').order_by('-captured_at').first())
    if proof:
        label = f'{proof.certificate.get_provider_display()} certificate' if proof.certificate_id else proof.get_kind_display()
        rows.append(row('Consent proof', f'{label}, captured {proof.captured_at:%d %b %H:%M:%S}', proof.source_system))
        if proof.certificate_id and proof.certificate.page:
            shot = PageCapture.objects.filter(client=client, page__address=proof.certificate.page, ok=True, captured_at__lt=end).order_by('-captured_at').first()
            if shot:
                rows.append(row('Consent page as of date', proof.certificate.page, f'Capture {shot.captured_at:%d %b} · Tier 1'))
    trace = Provenance.objects.filter(client=client, phone_token=token, first_contact_at__lt=end).order_by('-first_contact_at').first()
    if trace:
        rows.append(row('Lead source', trace.source_name or trace.get_basis_display(), trace.get_basis_display()))
    contact = ContactEvent.objects.filter(client=client, phone_token=token, occurred_at__lt=end).order_by('-occurred_at').first()
    if contact:
        rows.append(row('Contact log', f'{contact.get_channel_display()} {contact.occurred_at:%d %b %H:%M:%S}'
                        + (f' · {contact.dial_mode}' if contact.dial_mode else ''), f'{contact.source_system} · Tier {GRADE_TIER.get(contact.source_grade, 3)}'))
    stop = OptOutEvent.objects.filter(client=client, phone_token=token, at__lt=end).order_by('-at').first()
    rows.append(row('Opt-out history', f'{stop.get_method_display()} on {stop.at:%d %b %Y}' if stop else 'None on any channel at that date',
                    stop.source_system if stop else 'Your connected tools'))
    listed = InternalListEntry.objects.filter(client=client, phone_token=token, added_on__lte=day).exists()
    if InternalListEntry.objects.filter(client=client).exists():
        rows.append(row('Internal list', 'Listed' if listed else 'Not listed', 'Upload · Tier 4'))
    result = (ConsentResult.objects.filter(client=client, contact__phone_token=token, variant='strict', contact__occurred_at__lt=end)
              .order_by('-contact__occurred_at').first())
    if result:
        rows.append(row('Consent status', f'{result.status.upper()} · {result.primary_code}', f'Rulebook v{result.rulebook_version}'))
    covered = day >= client.start_date
    return {'phone': mask(number), 'date': day.isoformat(), 'insideCoverage': covered, 'rows': rows}


def hash_check(client, sha: str) -> dict:
    found = Fingerprint.objects.filter(client=client, sha256=sha.lower().strip()).select_related('anchor').first()
    if found is None:
        return {'found': False, 'artifact': None, 'capturedAt': None, 'anchoredOn': None, 'tier': None}
    return {'found': True, 'artifact': f'{found.source_system} · {found.source_record_id}', 'capturedAt': found.fetched_at,
            'anchoredOn': found.anchor.day.isoformat() if found.anchor_id else None, 'tier': GRADE_TIER.get(found.source_grade)}
