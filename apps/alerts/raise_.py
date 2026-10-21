"""Module 11 step 3: every 5 minutes, what needs a look is gathered into alerts (owner decision 2026-10-21):
High — a stop a tool never marked (Module 9), contacts after an opt-out, opted-out numbers brought back by a list;
Medium — consent wording changed, certificates expiring within 30 days, a tool stopped syncing, a month with
incomplete data. Conditions that last (a stale tool, an unmarked stop, an incomplete month) resolve by themselves;
events (contacts after an opt-out on a day) stay until reviewed."""
from datetime import timedelta

from django.utils import timezone

from apps.captures.api import wording_changed_on
from apps.captures.models import ConsentPage
from apps.certificates.models import CertificateClaim
from apps.connections.models import Connection, Status
from apps.consent.models import ConsentResult
from apps.optouts.models import MarkCheck, ReaddedNumber
from apps.reconcile.models import PeriodIntegrity

from .models import Alert

HIGH, MEDIUM = 'High', 'Medium'
RECENT = timedelta(days=7)  # events older than this when first seen raise no alert (e.g. at first sync)


def many(n: int, word: str) -> str:
    return f'{n:,} {word}' + ('' if n == 1 else 's')


def gather(client, now) -> dict[str, dict]:
    """{key: alert fields}; lasting=True means it resolves when no longer found."""
    out = {}
    for check in MarkCheck.objects.filter(client=client, marked=False, urgent_at__isnull=False).select_related('connection', 'optout'):
        out[f'unmarked-{check.optout_id}-{check.connection_id}'] = dict(
            kind='Opt-out not marked', severity=HIGH, domain='REV', lasting=True, at=check.urgent_at,
            title=f'A stop request is not marked in {check.connection.tool.name}',
            detail=f'Received {check.optout.at:%-d %b %H:%M} UTC; {check.connection.tool.name} still shows the number as contactable.')
    since = now - RECENT
    days = {}
    for r in ConsentResult.objects.filter(client=client, variant='strict', frozen=False, codes__contains=['NP_AFTER_OPT_OUT'],
                                          contact__occurred_at__gte=since).select_related('contact'):
        day = r.contact.occurred_at.date()
        days.setdefault(day, [set(), 0])
        days[day][0].add(r.contact.phone_token)
        days[day][1] += 1
    for day, (numbers, n) in days.items():
        out[f'after-optout-{day}'] = dict(kind='Contacts after opt-out', severity=HIGH, domain='REV', lasting=False, count=n,
                                         title=f'{many(n, "contact")} after an opt-out on {day:%-d %b}',
                                         detail=f'{many(n, "contact")} to {many(len(numbers), "number")} after they opted out.')
    found = {}
    for row in ReaddedNumber.objects.filter(client=client, found_at__gte=since):
        found.setdefault(row.found_at.date(), set()).add(row.phone_token)
    for day, numbers in found.items():
        out[f'readded-{day}'] = dict(kind='Opted-out numbers re-added', severity=HIGH, domain='REV', lasting=False, count=len(numbers),
                                    title=f'{many(len(numbers), "opted-out number")} brought back by an uploaded list',
                                    detail='An uploaded list included numbers that had opted out; contact to them would come after an opt-out.')
    for page in ConsentPage.objects.filter(client=client):
        changed = wording_changed_on(page)
        if changed and changed >= since:
            out[f'page-{page.pk}-{changed:%Y%m%d}'] = dict(kind='Consent page changed', severity=MEDIUM, domain='WEB', lasting=False, at=changed,
                                                         title=f'Consent wording changed on {page.address}',
                                                         detail=f'CiV\'s photo of {changed:%-d %b} shows different consent words than the one before.')
    soon = CertificateClaim.objects.filter(client=client, gone_at__isnull=True, cert_expires_at__gt=now, cert_expires_at__lte=now + timedelta(days=30)).count()
    if soon:
        out['certs-expiring'] = dict(kind='Certificate expiry', severity=MEDIUM, domain='CON', lasting=True, count=soon,
                                     title=f'{many(soon, "certificate")} become unavailable within 30 days',
                                     detail='After that the provider no longer shows them; CiV keeps its fingerprints.')
    for c in Connection.objects.filter(client=client, status=Status.STALE):
        out[f'stale-{c.pk}'] = dict(kind='Source stale', severity=MEDIUM, domain='REC', lasting=True,
                                    title=f'{c.tool.name} has stopped sending data',
                                    detail='Metrics that need it keep their last good values and are marked stale until it reconnects.')
    for month in PeriodIntegrity.objects.filter(client=client, incomplete=True):
        out[f'incomplete-{month.period:%Y-%m}'] = dict(kind='Incomplete data', severity=MEDIUM, domain='REC', lasting=True,
                                                      title=f'{month.period:%B %Y} is marked incomplete data',
                                                      detail=(f'CiV holds about {100 * month.completeness:.0f}% of the records your tools report. ' if month.completeness else '')
                                                      + 'The missing share counts at its worst case.')
    return out


def refresh(client, now=None) -> int:
    """Raise or update this client's alerts; resolve lasting ones no longer found. Returns how many are open."""
    now = now or timezone.now()
    found = gather(client, now)
    for key, f in found.items():
        lasting, at = f.pop('lasting'), f.pop('at', now)
        row = Alert.objects.filter(client=client, key=key).first()
        if row is None:
            Alert.objects.create(client=client, key=key, first_at=at, at=at, **f)
        elif any(getattr(row, k) != v for k, v in f.items()) or row.resolved_at:
            for k, v in f.items():
                setattr(row, k, v)
            row.at, row.resolved_at = now, None
            row.save()
    gone = Alert.objects.filter(client=client, resolved_at__isnull=True).exclude(key__in=found)
    lasting_prefixes = ('unmarked-', 'certs-expiring', 'stale-', 'incomplete-')
    for row in gone:
        if row.key.startswith(lasting_prefixes):
            row.resolved_at = now
            row.save(update_fields=['resolved_at'])
    return Alert.objects.filter(client=client, reviewed=False, resolved_at__isnull=True).count()
