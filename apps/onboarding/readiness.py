"""Setup & Readiness from what CiV really has: each readiness check (names as the portal shows them), the start
decision, numbers per month and the recommended plan, a preview of consent results on recent numbers, and the setup
checklist with its fixed labels. Recordings wait for Module 9; a check CiV cannot judge yet is left out."""
from collections import Counter
from datetime import timedelta

from django.utils import timezone

from apps.captures.models import ConsentPage, PageCapture
from apps.certificates.models import CertificateClaim
from apps.connections.models import Status
from apps.connections.providers import Kind
from apps.consent.models import ConsentProof, ConsentResult
from apps.contacts.models import ContactEvent
from apps.imports.models import CrmCreation
from apps.provenance.models import Provenance
from apps.sync.health import state as sync_state
from apps.sync.models import SyncCursor
from apps.uploads.models import Source, UploadedFile

PLANS = [('Starter', 10_000), ('Growth', 50_000), ('Scale', 250_000)]  # numbers contacted per month (feature guide)
SAMPLE = 100


def plan_for(numbers: int) -> str:
    return next((name for name, limit in PLANS if numbers <= limit), 'Enterprise')


def check(name, how, state, detail, fix=None):
    return {'name': name, 'how': how, 'state': state, 'detail': detail, 'fix': fix}


def connection_check(client, kind: str, name: str, what: str) -> dict:
    conns = [c for c in client.connections.all() if c.kind == kind]
    if not conns:
        return check(name, 'Not connected', 'missing', f'No {what} connected yet', 'Connect it on Source Registry.')
    live = [c for c in conns if c.status in (Status.CONNECTED, Status.STALE)
            and sync_state(SyncCursor.objects.filter(connection=c).first()) in ('live', 'catching_up')]
    if live:
        return check(name, f'Connected and read by API ({", ".join(c.tool.name for c in live)})', 'ready', 'Read in the last few minutes')
    return check(name, 'Connected', 'partial', 'Not read recently', 'Check the connection on Source Registry.')


def readiness(client) -> dict:
    now = timezone.now()
    month = ContactEvent.objects.filter(client=client, direction='outbound', is_primary=True, occurred_at__gte=now - timedelta(days=30))
    numbers = month.values('phone_token').distinct().count()
    checks = [connection_check(client, Kind.DIALER, 'Dialer connection', 'dialer'), connection_check(client, Kind.SMS, 'SMS connection', 'texting tool'),
              connection_check(client, Kind.CRM, 'CRM connection', 'CRM')]
    connected = any(c['state'] == 'ready' for c in checks[:2])  # a dialer or texting tool really read lately, not only saved
    calls = month.filter(channel='call')
    if calls.exists():
        missing = round(100 * calls.filter(dial_mode='').count() / calls.count())
        if missing:
            checks[0]['state'], checks[0]['detail'] = 'partial', f'Dial mode is missing on {missing}% of calls (counted as autodialed)'
            checks[0]['fix'] = 'Turn on the dial-mode field in your dialer, or tell CiV which calls are hand-dialed.'
    recent = list(month.order_by('-occurred_at').values_list('phone_token', flat=True).distinct()[:SAMPLE * 5])
    sample = list(dict.fromkeys(recent))[:SAMPLE]
    if sample:
        proven = ConsentProof.objects.filter(client=client, phone_token__in=sample, withdrawn_at__isnull=True).exclude(kind='self_asserted') \
            .values('phone_token').distinct().count()
        checks.append(check('Consent proof', f'Looked for a proof for {len(sample)} recent numbers', 'ready' if proven == len(sample) else 'partial' if proven else 'missing',
                            f'{proven} of {len(sample)} found', None if proven == len(sample) else 'Make sure every lead carries its certificate link.'))
    claims = CertificateClaim.objects.filter(client=client)
    if claims.exists():
        lost = claims.filter(state='lost').count()
        soon = claims.filter(state='claimed', cert_expires_at__lt=now + timedelta(days=365)).count()
        checks.append(check('Certificate retention', 'Checked each certificate CiV claimed', 'ready' if not (lost or soon) else 'partial',
                            f'{lost} not claimed in time · {soon} kept less than a year' if lost or soon else 'Every certificate claimed and kept',
                            None if not (lost or soon) else 'Retain certificates for five years in your certificate account.'))
    pages = ConsentPage.objects.filter(client=client)
    if pages.exists():
        shot = pages.filter(pk__in=PageCapture.objects.filter(client=client, ok=True).values('page_id')).count()
        checks.append(check('Consent pages', 'Photographed each known consent page', 'ready' if shot == pages.count() else 'partial',
                            f'{shot} of {pages.count()} pages captured', None if shot == pages.count() else 'Check the pages that could not be opened (Consent Integrity → Wording).'))
    traced = Provenance.objects.filter(client=client, first_contact_at__gte=now - timedelta(days=30))
    if traced.exists():
        untraced = traced.filter(basis='untraced').count()
        checks.append(check('Lead records', 'Traced each called number to its source', 'ready' if not untraced else 'partial',
                            f'{untraced} of {traced.count()} numbers untraced' if untraced else 'Every called number traced',
                            None if not untraced else 'Ask lead vendors to name themselves on every lead record.'))
    internal = UploadedFile.objects.filter(client=client, source=Source.INTERNAL_LIST).first()
    checks.append(check('Internal do-not-contact list', 'Uploaded and read' if internal else 'Not uploaded', 'ready' if internal else 'missing',
                        f'Uploaded {internal.received_at:%-d %b %Y} · {internal.rows_read:,} numbers' if internal else 'Not supplied',
                        None if internal else 'Upload it in Source Registry.'))
    first = ContactEvent.objects.filter(client=client).order_by('occurred_at').values_list('occurred_at', flat=True).first()
    if first:
        years = (now - first).days / 365
        checks.append(check('History depth', 'Earliest record CiV read', 'ready' if years >= 4 else 'partial',
                            f'Records reach back to {first:%b %Y}', None if years >= 4 else 'Ask your tools for older history: the time to sue is four years.'))
    dnc, rnd = (UploadedFile.objects.filter(client=client, source=s).exists() for s in (Source.DNC_CHECKS, Source.RND_QUERIES))
    missing_docs = [label for ok, label in ((dnc, 'DNC check records'), (rnd, 'reassigned-number query logs')) if not ok]
    checks.append(check('Documents', 'Checked uploads', 'ready' if not missing_docs else 'partial' if len(missing_docs) == 1 else 'missing',
                        (lambda t: t[:1].upper() + t[1:])(' and '.join(missing_docs)) + ' not supplied' if missing_docs else 'DNC check records and query logs supplied',
                        'Upload them in Source Registry.' if missing_docs else None))
    results = Counter(ConsentResult.objects.filter(client=client, variant='strict', contact__phone_token__in=sample, frozen=False)
                      .exclude(status__in=['pending', 'not_needed']).values_list('status', flat=True))
    return {'runOn': now.date().isoformat(), 'sampleNumbers': len(sample), 'checks': checks, 'canStart': connected,
            'numbersPerMonth': numbers, 'recommendedPlan': plan_for(numbers),
            'preview': [{'status': s.upper(), 'count': results.get(s, 0)} for s in ('verified', 'weak', 'conflicting', 'no_proof')] if results else [],
            'notMeasured': not_supplied(client), 'setup': setup_rows(client, month)}


def not_supplied(client) -> list[str]:
    """Metrics held at worst case or left unmeasured because an upload is missing."""
    have = set(UploadedFile.objects.filter(client=client).values_list('source', flat=True))
    rows = ((Source.RND_QUERIES, 'M11 Pre-Contact Reassigned Checks'), (Source.INTERNAL_LIST, 'M12 Internal List Contacts'),
            (Source.DNC_CHECKS, 'M13 DNC Scrub Record Check'))
    return [label for source, label in rows if source not in have]


# The Setup & Readiness checklist rows: id → (label, what it asks for).
SETUP_LABELS = {
    'outcomes': ('Outcome mapping', 'Which dialer outcomes mean “stop calling”'),
    'caller-ids': ('Caller IDs', 'Every number you show when calling'),
    'pages': ('Consent pages', 'Every address where you or your affiliates collect consent'),
    'vendors': ('Lead vendors and sub-IDs', 'Names and sub-IDs of every vendor and affiliate'),
    'campaigns': ('Campaign categories', 'Mark each campaign as marketing or informational'),
    'states': ('States and brands', 'States you call and the brand names you use'),
    'optout-methods': ('Designated opt-out methods', 'Whether you designate an exclusive opt-out method, and where it is disclosed'),
}
SETUP_ITEMS = tuple(SETUP_LABELS)


def setup_rows(client, month) -> list[dict]:
    """The setup checklist rows CiV can count itself (the others keep the client's own ticks)."""
    pages = ConsentPage.objects.filter(client=client).count()
    vendors = CrmCreation.objects.filter(client=client).exclude(vendor='').values('vendor').distinct().count()
    caller_ids = month.exclude(caller_id_token='').values('caller_id_token').distinct().count()
    campaigns = month.exclude(campaign='').values('campaign').distinct().count()
    states = month.exclude(recipient_state='').values('recipient_state').distinct().count()
    rows = []
    if caller_ids:
        rows.append({'id': 'caller-ids', 'done': True, 'count': f'{caller_ids} caller IDs'})
    if pages:
        rows.append({'id': 'pages', 'done': True, 'count': f'{pages} pages'})
    if vendors:
        rows.append({'id': 'vendors', 'done': True, 'count': f'{vendors} vendors'})
    if campaigns:  # owner decision: every campaign is treated as marketing (strictest), nothing to mark
        rows.append({'id': 'campaigns', 'done': True, 'count': f'{campaigns} campaigns · all treated as marketing'})
    if states:
        rows.append({'id': 'states', 'done': True, 'count': f'{states} states'})
    # Every other row is the Admin's own tick, saved per company (owner, 2026-10-23); never the sample's.
    from .models import SetupMark
    counted = {r['id'] for r in rows}
    marks = {m.item: m for m in SetupMark.objects.filter(client=client)}
    for item in SETUP_ITEMS:
        if item in counted:
            continue
        m = marks.get(item)
        rows.append({'id': item, 'done': bool(m and m.done),
                     'count': f"Marked {'done' if m.done else 'not done'} by {m.by} on {m.at:%-d %b %Y}" if m else 'Not marked yet'})
    order = {item: i for i, item in enumerate(SETUP_ITEMS)}
    return [{**r, 'label': SETUP_LABELS[r['id']][0], 'detail': SETUP_LABELS[r['id']][1]} for r in sorted(rows, key=lambda r: order[r['id']])]


USAGE_RULE = ('If numbers contacted exceed the plan limit two months in a row, the plan moves up from the next month. '
              'There are no overage charges.')


def usage(client) -> dict:
    """Plan & usage: distinct numbers contacted this month and the three before, against the plan's limit."""
    from apps.billing.models import Contract
    today = timezone.localdate()
    firsts = [today.replace(day=1)]
    for _ in range(3):
        firsts.insert(0, (firsts[0] - timedelta(days=1)).replace(day=1))
    history = []
    for first in firsts:
        nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        used = ContactEvent.objects.filter(client=client, direction='outbound', is_primary=True, occurred_at__date__gte=first,
                                           occurred_at__date__lt=nxt).values('phone_token').distinct().count()
        history.append({'label': first.strftime('%b'), 'used': used})
    plan = client.get_plan_display()
    limit = dict(PLANS).get(plan)
    over = 0
    for row in reversed(history):
        if limit and row['used'] > limit:
            over += 1
        else:
            break
    names = [p for p, _ in PLANS] + ['Enterprise']
    out = {'plan': plan, 'used': history[-1]['used'], 'history': history, 'overLimitMonths': over, 'limit': limit, 'monthlyPrice': None,
           'nextPlan': names[names.index(plan) + 1] if plan in names[:-1] else None, 'rule': USAGE_RULE}
    contract = Contract.objects.filter(client=client).first()
    if contract and contract.price is not None:  # the card says "<price> a month"
        per = {'monthly': 1, 'quarterly': 3, 'yearly': 12}.get(contract.billing_period, 1)
        symbol = '$' if contract.currency == 'USD' else f'{contract.currency} '
        out['monthlyPrice'] = f'{symbol}{contract.price / per:,.0f}'
    return out


def billed_numbers(client) -> list[tuple[str, str, int]]:
    """This month's billed numbers: masked label (never the number), first contact, contacts."""
    first = timezone.localdate().replace(day=1)
    rows = (ContactEvent.objects.filter(client=client, direction='outbound', is_primary=True, occurred_at__date__gte=first)
            .order_by('occurred_at').values_list('phone_token', 'masked_label', 'occurred_at'))
    seen: dict[str, list] = {}
    for token, label, at in rows:
        seen.setdefault(token, [label, at, 0])[2] += 1
    return [(label, f'{at:%Y-%m-%d}', n) for label, at, n in seen.values()]
