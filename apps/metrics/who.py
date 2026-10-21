"""Who You Contact: the checks that are real from what CiV holds (consent results, uploaded DNC check records and
internal list, reassigned-number query logs, CRM opt-out marks), over the last 30 days. Checks that need a later module
(AI review of replies, CiV's own reassigned-number queries, litigator lists, court dockets) are left out: the portal keeps
its sample for them until those modules exist. Names match the portal's check names so each one replaces its own row."""
import hashlib
from collections import Counter
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from apps.consent.models import ConsentResult
from apps.contacts.models import ContactEvent
from apps.imports.models import CrmCreation, CrmUpdate, ImportBatch
from apps.provenance.models import Provenance
from apps.uploads.models import DncCheck, InternalListEntry, RndQuery, Source, UploadedFile

from .models import LeadSourceCheck

DAYS = 30
MAX_AGE = 31  # dnc_check_max_age_days
COLUMNS = ('national', 'state', 'internal', 'reassigned')


def many(n: int, word: str) -> str:
    return f'{n:,} {word}' + ('' if n == 1 else 's')


def check(state, name, result, source, metric, why):
    return {'state': state, 'name': name, 'result': result, 'source': source, 'metric': metric, 'why': why}


def flag(c, known, source_name, flagged_on):
    return {'number': c.masked_label, 'known': known, 'from': source_name, 'flaggedOn': flagged_on.strftime('%b %-d'),
            'contactedOn': c.occurred_at.strftime('%b %-d'), 'channel': c.get_channel_display()}


def window(client):
    since = timezone.now() - timedelta(days=DAYS)
    return ContactEvent.objects.filter(client=client, direction='outbound', is_primary=True, is_test=False, occurred_at__gte=since)


def dnc_area(client, contacts) -> dict:
    checks, flags = [], []
    lapsed = ConsentResult.objects.filter(contact__in=contacts, variant='strict', frozen=False, codes__contains=['NP_RELATIONSHIP_LAPSED']).count()
    checks.append(check('fail' if lapsed else 'pass', 'Expired customer relationship used', many(lapsed, 'call') if lapsed else 'None', 'records', 'M40',
                        'Calls more than 3 months after an inquiry or 18 months after a purchase, from your CRM records.'))
    if not DncCheck.objects.filter(client=client).exists():
        return {'id': 'dnc', 'checks': checks}  # the DNC rows keep "not supplied" until DNC check records are uploaded
    total = covered = old = 0
    for c in contacts.only('phone_token', 'occurred_at', 'masked_label', 'channel'):
        day = c.occurred_at.date()
        latest = DncCheck.objects.filter(client=client, phone_token=c.phone_token, checked_on__lte=day).order_by('-checked_on').first()
        total += 1
        if latest and (day - latest.checked_on).days <= MAX_AGE:
            covered += 1
        elif latest:
            old += 1
        listed = DncCheck.objects.filter(client=client, phone_token=c.phone_token, checked_on__lte=day, listed=True).order_by('checked_on').first()
        if listed:
            flags.append(flag(c, f'Flagged by your DNC check ({listed.list_name})', 'Your DNC check records', listed.checked_on))
    share = round(100 * covered / total) if total else 100
    checks.append(check('pass' if share >= 99 else 'warn' if share >= 90 else 'fail', 'National registry checked', f'{share}% of contacts', 'list', 'M13',
                        f'{covered:,} of {total:,} contacts had a DNC check within {MAX_AGE} days before them.'))
    checks.append(check('fail' if flags else 'pass', 'Called after your provider flagged the number', many(len(flags), 'contact') if flags else 'None',
                        'list', 'M39', 'Contacts after your DNC check said the number is listed.'))
    checks.append(check('warn' if old else 'pass', 'Registry copy older than 31 days', many(old, 'contact') if old else 'None', 'list', 'M49',
                        'The law allows a copy no more than 31 days old.'))
    states = sorted({n for n in DncCheck.objects.filter(client=client).exclude(list_name__iexact='national').values_list('list_name', flat=True) if n})
    if states:
        checks.append(check('pass', 'State lists checked (CA, AZ, TX, FL, NV)', 'Checked: ' + ', '.join(states[:8]), 'list', 'M13',
                            'From your DNC check records.'))
    return {'id': 'dnc', 'checks': checks, 'flags': flags[:50]}


def internal_area(client, contacts) -> dict:
    checks = []
    removed = CrmUpdate.objects.filter(client=client, cleared_optout=True).count()
    checks.append(check('fail' if removed else 'pass', 'Removed from the list too early', many(removed, 'number') if removed else 'None', 'records', 'M44',
                        'Opt-out marks cleared in your CRM (for example by a re-uploaded sheet). Requests must be honored for 5 years.'))
    if not InternalListEntry.objects.filter(client=client).exists():
        return {'id': 'idn', 'checks': checks}
    flags, numbers = [], set()
    for c in contacts.only('phone_token', 'occurred_at', 'masked_label', 'channel'):
        entry = InternalListEntry.objects.filter(client=client, phone_token=c.phone_token, added_on__lte=c.occurred_at.date()).order_by('added_on').first()
        if entry:
            numbers.add(c.phone_token)
            flags.append(flag(c, 'Joined your do-not-call list', 'Your internal list', entry.added_on))
    last = UploadedFile.objects.filter(client=client, source=Source.INTERNAL_LIST).first()
    checks.insert(0, check('fail' if flags else 'pass', 'Called after joining your list', many(len(flags), 'contact') if flags else 'None', 'list', 'M12',
                           f'{len(numbers):,} numbers were contacted after they joined your list (uploaded {last.received_at:%-d %b}).'))
    return {'id': 'idn', 'checks': checks, 'flags': flags[:50]}


def reassigned_area(client, contacts) -> dict:
    checks = []
    results = ConsentResult.objects.filter(contact__in=contacts, variant='strict', proof__isnull=False).select_related('proof', 'contact')
    total = old = 0
    for r in results:
        when = r.proof.when()
        if when:
            total += 1
            old += (r.contact.occurred_at - when).days > 365
    if total:
        share = round(100 * old / total)
        checks.append(check('warn' if share else 'pass', 'Consent older than 12 months', f'{share}%', 'records', 'M47',
                            'Older consent means more numbers have changed hands.'))
    if RndQuery.objects.filter(client=client).exists():
        asked = sum(1 for c in contacts.only('phone_token', 'occurred_at') if RndQuery.objects.filter(
            client=client, phone_token=c.phone_token, result='no', queried_on__lte=c.occurred_at.date(),
            queried_on__gte=c.occurred_at.date() - timedelta(days=31)).exists())
        n = contacts.count()
        share = round(100 * asked / n) if n else 100
        checks.append(check('pass' if share >= 99 else 'warn', 'Covered by the safe harbor', f'{share}% of contacts', 'list', 'M11',
                            'Contacts preceded by your own reassigned-number check (answer "no") within the month before.'))
    return {'id': 'rnd', 'checks': checks}


def services(client) -> list[dict]:
    def note(source, blocks):
        last = UploadedFile.objects.filter(client=client, source=source).first()
        if last is None:
            return f'Not supplied · blocks {blocks}'
        rows = {Source.INTERNAL_LIST: InternalListEntry, Source.DNC_CHECKS: DncCheck, Source.RND_QUERIES: RndQuery}[source]
        count = rows.objects.filter(client=client).values('phone_token').distinct().count()
        return f'Uploaded {last.received_at:%-d %b} · {count:,} numbers'
    dnc = DncCheck.objects.filter(client=client)
    return [
        {'name': 'DNC check records', 'note': note(Source.DNC_CHECKS, 'M13'),
         'covers': {'national': 'list' if dnc.filter(list_name__iexact='national').exists() else 'none',
                    'state': 'list' if dnc.exclude(list_name__iexact='national').exists() else 'stated'}},
        {'name': 'Internal do-not-contact list', 'note': note(Source.INTERNAL_LIST, 'M12'),
         'covers': {'internal': 'list' if InternalListEntry.objects.filter(client=client).exists() else 'none'}},
        {'name': 'Reassigned-number query logs', 'note': note(Source.RND_QUERIES, 'M11'),
         'covers': {'reassigned': 'list' if RndQuery.objects.filter(client=client).exists() else 'none'}},
    ]


def source_id(key: str) -> str:
    return 'ls-' + hashlib.sha256(key.encode()).hexdigest()[:12]  # stable across uploads and batch rebuilds


def lead_sources(client) -> list[dict]:
    """Vendors the CRM names (and websites when none is named), and each uploaded list, with the client's own switches."""
    marks = {(m.source_key, m.column): m.checked for m in LeadSourceCheck.objects.filter(client=client)}
    rows = []
    vendors = Counter(CrmCreation.objects.filter(client=client).exclude(vendor='').values_list('vendor', flat=True))
    if not vendors:
        vendors = Counter(dict(Provenance.objects.filter(client=client, basis='cert_domain').values_list('source_name')
                               .annotate(n=Count('id')).values_list('source_name', 'n')))
    for name, n in vendors.most_common(20):
        key = f'vendor:{name}'
        rows.append({'id': source_id(key), 'key': key, 'group': 'vendor', 'name': name, 'note': f'{n:,} leads',
                     'checked': {col: marks.get((key, col), False) for col in COLUMNS}})
    for batch in ImportBatch.objects.filter(client=client, kind__in=[ImportBatch.Kind.BULK, ImportBatch.Kind.SMALL]).order_by('-starts')[:20]:
        key = f'upload:{batch.system}|{batch.source_system}|{batch.created_by or batch.list_id}|{batch.starts:%Y%m%dT%H%M%S}'
        size = batch.updated_count if batch.system == 'crm_update' else batch.created_count
        rows.append({'id': source_id(key), 'key': key, 'group': 'upload', 'name': f'Uploaded list · {batch.starts:%-d %b %Y}',
                     'note': f'{size:,} numbers', 'checked': {col: marks.get((key, col), False) for col in COLUMNS}})
    return rows


def who_contact(client) -> dict:
    contacts = window(client)
    # An empty list would wipe the portal's rows for checks not built yet: leave out empty parts, and areas with nothing real.
    areas = [{k: v for k, v in a.items() if v != []} for a in (dnc_area(client, contacts), internal_area(client, contacts), reassigned_area(client, contacts))]
    return {'areas': [a for a in areas if 'checks' in a],
            'services': services(client), 'leadSources': lead_sources(client)}
