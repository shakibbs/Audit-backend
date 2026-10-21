"""Module 13 step 5: the Rulebook check for CiV staff (owner decision 2026-10-22) — rules that change results but are
still not set ("needs a decision"), with how many active clients contacted where they apply in the last 30 days;
rules that change results but are only Proposed and not confirmed by a lawyer; the count by status; and each rule's
history (every value with its dates)."""
from collections import Counter
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from apps.contacts.models import ContactEvent

from .lookup import current_version
from .models import RuleValue


def place(jurisdiction: str) -> str:
    return 'Federal' if jurisdiction == 'US' else jurisdiction


def in_force(version, today) -> list[RuleValue]:
    return [r for r in RuleValue.objects.filter(version=version)
            if (r.effective_from is None or r.effective_from <= today) and (r.effective_to is None or today <= r.effective_to)]


def affected_clients(rows: list[RuleValue], since) -> dict[str, int]:
    """{jurisdiction: active clients that contacted it in the last 30 days}; US = every client with a contact."""
    from apps.tenancy.scope import all_clients
    with all_clients():
        recent = ContactEvent.objects.filter(occurred_at__gte=since, direction='outbound', client__is_active=True)
        by_state = Counter(dict(recent.exclude(recipient_state='').values('recipient_state')
                                .annotate(n=Count('client', distinct=True)).values_list('recipient_state', 'n')))
        everyone = recent.values('client').distinct().count()
    return {r.jurisdiction: (everyone if r.jurisdiction == 'US' else by_state.get(r.jurisdiction, 0)) for r in rows}


def check(today=None) -> dict:
    today = today or timezone.localdate()
    version = current_version('internal')
    rows = in_force(version, today)
    pending = [r for r in rows if r.status == 'tbd' and r.affects_status]
    unconfirmed = [r for r in rows if r.status == 'proposed' and r.affects_status and not r.counsel_approved]
    clients = affected_clients(pending, timezone.now() - timedelta(days=30))
    us = Counter(r.status for r in rows if r.jurisdiction == 'US')
    return {
        'version': version,
        'counts': {'set': us.get('set', 0), 'proposed': us.get('proposed', 0), 'tbd': us.get('tbd', 0)},
        'pending': sorted(({'key': r.key, 'place': place(r.jurisdiction), 'meaning': r.meaning, 'owner': r.get_owner_display(),
                            'counsel_item': r.counsel_item, 'clients': clients.get(r.jurisdiction, 0)} for r in pending),
                          key=lambda x: (-x['clients'], x['key'], x['place'])),
        'unconfirmed': sorted(({'key': r.key, 'place': place(r.jurisdiction), 'shown': r.shown, 'owner': r.get_owner_display(),
                                'counsel_item': r.counsel_item} for r in unconfirmed), key=lambda x: (x['key'], x['place'])),
    }


def history(key: str) -> list[dict]:
    from datetime import date
    rows = sorted(RuleValue.objects.filter(key=key).select_related('version'),
                  key=lambda r: (r.jurisdiction != 'US', r.jurisdiction, r.effective_from or date.min))  # no start date = from the start
    return [{'place': place(r.jurisdiction), 'shown': r.shown, 'status': r.get_status_display(), 'from': r.effective_from, 'to': r.effective_to,
             'version': r.version.version, 'changed_by': r.changed_by, 'approved_by': r.approved_by, 'source': r.source_url} for r in rows]
