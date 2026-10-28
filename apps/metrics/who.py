"""Who You Contact: every check of the four areas, over the last 30 days, from what CiV holds (consent results, uploaded
DNC check records and internal list, reassigned-number query logs, CRM opt-out marks, AI review). A check CiV cannot
run yet (it needs data the client has not supplied, or a later module) is sent as "Not measured", never with a result."""
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
    return {'state': state, 'name': name, 'result': result, 'source': source, 'metric': metric, 'why': why, 'isNew': False}


def unmeasured(name, metric, why):
    return check('unverified', name, 'Not measured', 'none', metric, why)


def flag(c, known, source_name, flagged_on):
    return {'number': c.masked_label, 'known': known, 'from': source_name, 'flaggedOn': flagged_on.strftime('%b %-d'),
            'contactedOn': c.occurred_at.strftime('%b %-d'), 'channel': c.get_channel_display()}


def window(client):
    since = timezone.now() - timedelta(days=DAYS)
    return ContactEvent.objects.filter(client=client, direction='outbound', is_primary=True, is_test=False, occurred_at__gte=since)


def dnc_area(client, contacts) -> dict:
    checks, flags = [], []
    lapsed = ConsentResult.objects.filter(contact__in=contacts, variant='strict', frozen=False, codes__contains=['NP_RELATIONSHIP_LAPSED']).count()
    if contacts.exists():
        checks.append(check('fail' if lapsed else 'pass', 'Expired customer relationship used', many(lapsed, 'call') if lapsed else 'None', 'records', 'M40',
                            'Calls more than 3 months after an inquiry or 18 months after a purchase, from your CRM records.'))
    else:
        checks.append(unmeasured('Expired customer relationship used', 'M40', f'No contacts in the last {DAYS} days to check.'))
    if not DncCheck.objects.filter(client=client).exists():
        why = 'Your DNC check records are not supplied. Upload them on the Source Registry.'
        return {'id': 'dnc', 'checks': checks + [unmeasured('National registry checked', 'M13', why),
                                                 unmeasured('Called after your provider flagged the number', 'M39', 'Needs your DNC check records.'),
                                                 unmeasured('Registry copy older than 31 days', 'M49', 'Needs your DNC check records. The law allows a copy no more than 31 days old.'),
                                                 unmeasured('State lists checked', 'M13', 'Needs your DNC check records.')], 'flags': []}
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
    if total:
        share = round(100 * covered / total)
        checks.append(check('pass' if share >= 99 else 'warn' if share >= 90 else 'fail', 'National registry checked', f'{share}% of contacts', 'list', 'M13',
                            f'{covered:,} of {total:,} contacts had a DNC check within {MAX_AGE} days before them.'))
    else:
        checks.append(unmeasured('National registry checked', 'M13', f'No contacts in the last {DAYS} days to check.'))
    checks.append(check('fail' if flags else 'pass', 'Called after your provider flagged the number', many(len(flags), 'contact') if flags else 'None',
                        'list', 'M39', 'Contacts after your DNC check said the number is listed.'))
    checks.append(check('warn' if old else 'pass', 'Registry copy older than 31 days', many(old, 'contact') if old else 'None', 'list', 'M49',
                        'The law allows a copy no more than 31 days old.'))
    states = sorted({n for n in DncCheck.objects.filter(client=client).exclude(list_name__iexact='national').values_list('list_name', flat=True) if n})
    called = sorted({s for s in contacts.exclude(recipient_state='').values_list('recipient_state', flat=True)})
    missing = [st for st in called if st not in states]
    if states:
        checks.append(check('warn' if missing else 'pass', 'State lists checked', 'Checked: ' + ', '.join(states[:8]), 'list', 'M13',
                            f'From your DNC check records. Called but not checked: {", ".join(missing[:8])}.' if missing else 'From your DNC check records.'))
    else:
        checks.append(unmeasured('State lists checked', 'M13', 'Your DNC check records name no state list.'))
    return {'id': 'dnc', 'checks': checks, 'flags': flags[:50]}


def internal_area(client, contacts) -> dict:
    checks = []
    removed = CrmUpdate.objects.filter(client=client, cleared_optout=True).count()
    checks.append(check('fail' if removed else 'pass', 'Removed from the list too early', many(removed, 'number') if removed else 'None', 'records', 'M44',
                        'Opt-out marks cleared in your CRM (for example by a re-uploaded sheet). Requests must be honored for 5 years.'))
    stop_checks, stop_flags = stops_reached(client, contacts)
    checks += stop_checks
    checks.append(unmeasured('Called by another of your brands', 'M43', 'Comes when CiV reads more than one of your brands.'))
    if not InternalListEntry.objects.filter(client=client).exists():
        checks.insert(0, unmeasured('Called after joining your list', 'M12', 'Your internal do-not-call list is not supplied. Upload it on the Source Registry.'))
        return {'id': 'idn', 'checks': checks, 'flags': stop_flags}
    flags, numbers = [], set()
    for c in contacts.only('phone_token', 'occurred_at', 'masked_label', 'channel'):
        entry = InternalListEntry.objects.filter(client=client, phone_token=c.phone_token, added_on__lte=c.occurred_at.date()).order_by('added_on').first()
        if entry:
            numbers.add(c.phone_token)
            flags.append(flag(c, 'Joined your do-not-call list', 'Your internal list', entry.added_on))
    last = UploadedFile.objects.filter(client=client, source=Source.INTERNAL_LIST).first()
    if not contacts.exists():
        checks.insert(0, unmeasured('Called after joining your list', 'M12', f'No contacts in the last {DAYS} days to check.'))
        return {'id': 'idn', 'checks': checks, 'flags': stop_flags}
    checks.insert(0, check('fail' if flags else 'pass', 'Called after joining your list', many(len(flags), 'contact') if flags else 'None', 'list', 'M12',
                           f'{len(numbers):,} numbers were contacted after they joined your list (uploaded {last.received_at:%-d %b}).'))
    return {'id': 'idn', 'checks': checks, 'flags': (flags + stop_flags)[:50]}


def ai_running(client) -> bool:
    from apps.conversations.models import ConversationReview
    return ConversationReview.objects.filter(client=client).exclude(result='not_reviewed').exists()


def stops_reached(client, contacts) -> tuple[list, list]:
    """M41 stop requests (texted STOP or said in plain words) that never reached every tool by the deadline, and M42 the
    share marked in time (Module 9 step 3 checks). Only opt-outs that count; left out until there is something checked."""
    from statistics import median

    from apps.conversations.models import ConversationReview
    from apps.optouts.models import OptOutEvent
    since = timezone.now() - timedelta(days=DAYS)
    asked = OptOutEvent.objects.filter(client=client, counts=True, method__in=['keyword', 'ai'], at__gte=since).prefetch_related('mark_checks')
    checked = [e for e in asked if any(c.marked is not None for c in e.mark_checks.all())]
    if not checked and not ai_running(client):
        return [unmeasured('Stop requests that never reached your list', 'M41', 'No stop request checked in your tools yet.'),
                unmeasured('Added within 10 business days', 'M42', 'No stop request checked in your tools yet.')], []
    never = [e for e in checked if any(c.missed for c in e.mark_checks.all())]
    read = ConversationReview.objects.filter(client=client, reviewed_at__gte=since).exclude(result='not_reviewed').count()
    out = [check('fail' if never else 'pass', 'Stop requests that never reached your list', f'{len(never):,} of {len(checked):,}', 'records', 'M41',
                 f'{many(len(checked), "stop request")} checked in your tools ({read:,} calls and texts reviewed by AI); '
                 f'{len(never):,} never reached every tool by the deadline.')]
    now = timezone.now()
    due = [e for e in checked if all(c.deadline_at and c.deadline_at <= now for c in e.mark_checks.all() if c.marked is not None)]
    if due:
        late = [e for e in due if any(c.missed for c in e.mark_checks.all())]
        share = round(100 * (len(due) - len(late)) / len(due))
        days = [(max(c.marked_at for c in e.mark_checks.all() if c.marked_at) - e.at).total_seconds() / 86400
                for e in due if any(c.marked_at for c in e.mark_checks.all())]
        why = f'{len(late):,} {"was" if len(late) == 1 else "were"} late.' + (f' Median is {median(days):.0f} days.' if days else '')
        out.append(check('pass' if share == 100 else 'warn', 'Added within 10 business days', f'{share}%', 'records', 'M42', why))
    else:
        out.append(unmeasured('Added within 10 business days', 'M42', 'No deadline has passed yet.'))
    flags = [flag(c, 'Asked to stop, never added', 'AI review' if e.method == 'ai' else 'Texting tool replies', e.at)
             for e in never for c in contacts.filter(phone_token=e.phone_token, occurred_at__gt=e.at)[:3]]
    return out, flags


def wrong_number_check(client, contacts) -> tuple[list, list]:
    """M48: contacts after the person said "wrong number" (AI review, counted only after the exam)."""
    from apps.optouts.models import OptOutEvent
    told = list(OptOutEvent.objects.filter(client=client, counts=True, method='ai', keyword='wrong number'))
    if not told and not ai_running(client):
        return [unmeasured('Contacted after a “wrong number” reply', 'M48', 'Comes with AI review of calls and texts.')], []
    flags = [flag(c, 'Replied “wrong number”', 'AI review', e.at) for e in told for c in contacts.filter(phone_token=e.phone_token, occurred_at__gt=e.at)]
    return [check('fail' if flags else 'pass', 'Contacted after a “wrong number” reply', many(len(flags), 'contact') if flags else 'None', 'records', 'M48',
                  'Once you are told the number changed hands, the safe harbor no longer applies.')], flags


def litigation_area(client, contacts) -> dict:
    """M45: people who named a lawyer in a call or text (AI review, after its exam) and were contacted again. Demand letters
    in the complaint log are not counted yet (the log has no letter type)."""
    from apps.conversations.models import ConversationReview
    named = {}
    for r in ConversationReview.objects.filter(client=client, trusted=True, attorney_at__isnull=False).order_by('attorney_at'):
        named.setdefault(r.phone_token, r.attorney_at)
    later = [unmeasured('Numbers on your litigator list contacted', 'M14', 'Your litigator list is not supplied.'),
             unmeasured('Claims from serial plaintiffs', 'M46', 'Comes with court docket data.')]
    if not named and not ai_running(client):
        return {'id': 'lit', 'checks': [unmeasured('Contacted after naming an attorney', 'M45', 'Comes with AI review of calls and texts.')] + later, 'flags': []}
    flags = [flag(c, 'Named an attorney', 'AI review', at) for token, at in named.items()
             for c in contacts.filter(phone_token=token, occurred_at__gt=at)[:3]]
    again = len({f['number'] for f in flags})
    return {'id': 'lit', 'checks': [check('fail' if again else 'pass', 'Contacted after naming an attorney', f'{again:,} of {len(named):,}', 'records', 'M45',
                                          f'{many(len(named), "person")} named an attorney in a call or text; {again:,} contacted again.')] + later,
            'flags': flags[:50]}


def reassigned_area(client, contacts) -> dict:
    checks = []
    results = ConsentResult.objects.filter(contact__in=contacts, variant='strict', proof__isnull=False).select_related('proof', 'contact')
    total = old = 0
    for r in results:
        when = r.proof.when()
        if when:
            total += 1
            old += (r.contact.occurred_at - when).days > 365
    checks.append(unmeasured('Contacted after the RND said the owner changed', 'M35', 'Comes when CiV reads reassigned-number results itself.'))
    n = contacts.count()
    if not RndQuery.objects.filter(client=client).exists():
        checks.append(unmeasured('Covered by the safe harbor', 'M11', 'Your reassigned-number query logs are not supplied.'))
    elif not n:
        checks.append(unmeasured('Covered by the safe harbor', 'M11', f'No contacts in the last {DAYS} days to check.'))
    else:
        asked = sum(1 for c in contacts.only('phone_token', 'occurred_at') if RndQuery.objects.filter(
            client=client, phone_token=c.phone_token, result='no', queried_on__lte=c.occurred_at.date(),
            queried_on__gte=c.occurred_at.date() - timedelta(days=31)).exists())
        share = round(100 * asked / n)
        checks.append(check('pass' if share >= 99 else 'warn', 'Covered by the safe harbor', f'{share}% of contacts', 'list', 'M11',
                            'Contacts preceded by your own reassigned-number check (answer "no") within the month before.'))
    if total:
        share = round(100 * old / total)
        checks.append(check('warn' if share else 'pass', 'Consent older than 12 months', f'{share}%', 'records', 'M47',
                            'Older consent means more numbers have changed hands.'))
    else:
        checks.append(unmeasured('Consent older than 12 months', 'M47', 'No consent proof with a date among the contacts.'))
    wrong_checks, wrong_flags = wrong_number_check(client, contacts)
    return {'id': 'rnd', 'checks': wrong_checks + checks, 'flags': wrong_flags[:50]}


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
    """Vendors the CRM names or the client's uploaded vendor lead files name (websites when none is named), and each
    uploaded list (CRM import batches and Upload centre vendor lead files), with the client's own switches.
    Owner, 2026-10-24: lead files uploaded to CiV are shown and managed like the CRM's vendors and lists."""
    from apps.vendors.models import VendorLead
    marks = {(m.source_key, m.column): m.checked for m in LeadSourceCheck.objects.filter(client=client)}
    rows = []
    vendors: dict[str, list] = {}  # name in lower case → [name as first seen, leads]
    for name, n in list(Counter(CrmCreation.objects.filter(client=client).exclude(vendor='').values_list('vendor', flat=True)).items()) \
            + list(Counter(VendorLead.objects.filter(client=client).exclude(vendor='').values_list('vendor', flat=True)).items()):
        found = vendors.setdefault(' '.join(name.split()).lower(), [' '.join(name.split()), 0])
        found[1] += n
    if not vendors:
        for name, n in Provenance.objects.filter(client=client, basis='cert_domain').values_list('source_name').annotate(n=Count('id')).values_list('source_name', 'n'):
            vendors[name.lower()] = [name, n]
    for name, n in sorted(vendors.values(), key=lambda v: -v[1])[:20]:
        key = f'vendor:{name}'
        rows.append({'id': source_id(key), 'key': key, 'group': 'vendor', 'name': name, 'note': many(n, 'lead'),
                     'checked': {col: marks.get((key, col), False) for col in COLUMNS}})
    lists = []
    for batch in ImportBatch.objects.filter(client=client, kind__in=[ImportBatch.Kind.BULK, ImportBatch.Kind.SMALL]).order_by('-starts')[:20]:
        key = f'upload:{batch.system}|{batch.source_system}|{batch.created_by or batch.list_id}|{batch.starts:%Y%m%dT%H%M%S}'
        size = batch.updated_count if batch.system == 'crm_update' else batch.created_count
        lists.append((batch.starts, {'id': source_id(key), 'key': key, 'group': 'upload', 'name': f'Uploaded list · {batch.starts:%-d %b %Y}',
                                     'note': f'{size:,} numbers', 'checked': {col: marks.get((key, col), False) for col in COLUMNS}}))
    for upload in UploadedFile.objects.filter(client=client, source=Source.VENDOR_LEADS).order_by('-received_at')[:20]:
        key = f'upload:file|{upload.pk}'
        numbers = VendorLead.objects.filter(upload=upload).values('phone_token').distinct().count()
        lists.append((upload.received_at, {'id': source_id(key), 'key': key, 'group': 'upload',
                                           'name': f'Vendor lead file · {upload.received_at:%-d %b %Y}',
                                           'note': f'{many(numbers, "number")} · {upload.original_name}'[:120],
                                           'checked': {col: marks.get((key, col), False) for col in COLUMNS}}))
    rows += [row for _, row in sorted(lists, key=lambda t: t[0], reverse=True)[:20]]
    return rows


AREAS = {'dnc': ('National & state DNC', '47 C.F.R. §64.1200(c)(2)'), 'idn': ('Internal do-not-call', '47 C.F.R. §64.1200(d)'),
         'rnd': ('Reassigned numbers', '47 C.F.R. §64.1200(m)'), 'lit': ('Litigation signals', 'Targeting multiplier')}


def who_contact(client) -> dict:
    contacts = window(client)
    areas = [dnc_area(client, contacts), internal_area(client, contacts), reassigned_area(client, contacts), litigation_area(client, contacts)]
    return {'areas': [{'flags': [], **a, 'title': AREAS[a['id']][0], 'law': AREAS[a['id']][1]} for a in areas],
            'services': services(client), 'leadSources': lead_sources(client)}
