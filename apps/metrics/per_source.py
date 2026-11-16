"""Who checked what → what CiV found for each vendor and each uploaded list (owner 2026-11-16). For every number called
in the month: was it checked against each list before its first contact in the month? The facts are read once per
kind of file (one query each, no per-contact lookups), then each source adds up the facts of its own numbers.

A list with no file is "Can't tell"; a DNC file with national rows only makes State "Not checked"."""
from collections import defaultdict
from datetime import timedelta

from django.db.models import Max, Min
from django.db.models.functions import TruncDate

from apps.uploads.models import DncCheck, InternalListEntry, RndQuery

MAX_AGE = timedelta(days=31)


class Facts:
    """Per number called in the month: first and last contact day, and which checks were done in time."""
    def __init__(self, client, contacts):
        days = contacts.values('phone_token').annotate(first=Min(TruncDate('occurred_at')), last=Max(TruncDate('occurred_at')))
        self.first, self.last = {}, {}
        for row in days:
            self.first[row['phone_token']], self.last[row['phone_token']] = row['first'], row['last']
        called = contacts.values('phone_token')
        dnc = DncCheck.objects.filter(client=client)
        self.has_dnc = dnc.exists()
        self.has_state = dnc.exclude(list_name='').exclude(list_name__iexact='national').exists()
        self.has_internal = InternalListEntry.objects.filter(client=client).exists()
        self.has_rnd = RndQuery.objects.filter(client=client).exists()
        self.national, self.state, self.rnd = set(), set(), set()
        self.on_list: dict[str, object] = {}  # number → the day it joined the client's list
        for token, day, name in dnc.filter(phone_token__in=called).values_list('phone_token', 'checked_on', 'list_name'):
            if self._in_time(token, day):
                (self.national if name.lower() in ('', 'national') else self.state).add(token)
        for token, day in RndQuery.objects.filter(client=client, result=RndQuery.Result.NO, phone_token__in=called).values_list('phone_token', 'queried_on'):
            if self._in_time(token, day):
                self.rnd.add(token)
        for token, added in InternalListEntry.objects.filter(client=client, phone_token__in=called).values_list('phone_token', 'added_on'):
            if added <= self.last.get(token, added - timedelta(days=1)):  # on the list before a contact in the month
                self.on_list[token] = min(added, self.on_list.get(token, added))

    def _in_time(self, token, day) -> bool:
        first = self.first.get(token)
        return first is not None and first - MAX_AGE <= day <= first

    def found(self, tokens: set[str] | None) -> dict:
        """What CiV found for one source, per list. None (numbers unknown) = "Can't tell" everywhere."""
        if tokens is None:
            cant = {'tone': 'gray', 'text': "Can't tell · its numbers are not known"}
            return {c: dict(cant) for c in ('national', 'state', 'internal', 'reassigned')}
        called = {t for t in tokens if t in self.first}
        n = len(called)

        def share(done: set, missing_file: str) -> dict:
            if missing_file:
                return {'tone': 'gray', 'text': f"Can't tell · {missing_file}"}
            if not n:
                return {'tone': 'gray', 'text': 'None of its numbers were called'}
            ok = len(called & done)
            tone = 'ok' if 100 * ok >= 99 * n else 'warn' if ok else 'bad'
            return {'tone': tone, 'text': f'of {n:,} numbers called were checked', 'checked': ok, 'total': n,
                    **({'count': {'n': n - ok, 'label': 'not checked'}} if ok < n else {})}

        state = share(self.state, '' if self.has_dnc else 'no DNC check file')
        if self.has_dnc and not self.has_state:
            state = {'tone': 'bad', 'text': 'No state check found'}
        if not self.has_internal:
            internal = {'tone': 'gray', 'text': "Can't tell · no internal list"}
        elif not n:
            internal = {'tone': 'gray', 'text': 'None of its numbers were called'}
        else:
            still = len(called & self.on_list.keys())
            internal = {'tone': 'bad', 'text': 'on your list still called', 'count': {'n': still, 'label': 'on your list still called'}} if still \
                else {'tone': 'ok', 'text': 'None on your list called'}
        return {'national': share(self.national, '' if self.has_dnc else 'no DNC check file'), 'state': state, 'internal': internal,
                'reassigned': share(self.rnd, '' if self.has_rnd else 'no query logs')}

    def missed(self, tokens: set[str], col: str) -> set[str]:
        """The numbers behind a count: called but not checked, or (internal) on the list and still called."""
        called = {t for t in tokens if t in self.first}
        if col == 'internal':
            return called & self.on_list.keys()
        return called - {'national': self.national, 'state': self.state, 'reassigned': self.rnd}[col]


def tokens_by_vendor(client) -> dict[str, set[str]]:
    """Numbers per vendor name (lower case), from CRM leads and uploaded vendor lead files."""
    from apps.imports.models import CrmCreation
    from apps.vendors.models import VendorLead
    out: dict[str, set[str]] = defaultdict(set)
    for vendor, tokens in CrmCreation.objects.filter(client=client).exclude(vendor='').values_list('vendor', 'phone_tokens'):
        out[' '.join(vendor.split()).lower()].update(tokens or [])
    for vendor, token in VendorLead.objects.filter(client=client).exclude(vendor='').values_list('vendor', 'phone_token'):
        out[' '.join(vendor.split()).lower()].add(token)
    return out


SHOWN = 100
WHY = {'national': 'No national do-not-call check in the 31 days before', 'state': 'No state do-not-call check in the 31 days before',
       'reassigned': 'No "not reassigned" answer in the 31 days before'}


def numbers(client, period: str | None, source: str, col: str) -> dict | None:
    """The phone numbers behind a count on Who You Contact (owner 2026-11-16), masked as everywhere in the portal: for
    "all" the glance (every number contacted), otherwise one vendor or uploaded list. At most 100 rows; total is all."""
    from apps.contacts.models import ContactEvent

    from .who import Span, lead_sources, window
    span = Span(period)
    contacts = window(client, span)
    facts = Facts(client, contacts)
    if source == 'all':
        tokens, name = set(facts.first), 'All sources'
    else:
        row = next((r for r in lead_sources(client, contacts, keep_tokens=True) if r['id'] == source), None)
        if row is None:
            return None
        tokens, name = row['_tokens'] or set(), row['name']
    missed = facts.missed(tokens, col)
    ordered = sorted(missed, key=lambda t: (facts.first[t], t))[:SHOWN]
    first = {}
    for token, label, at, channel in ContactEvent.objects.filter(pk__in=contacts.filter(phone_token__in=ordered).values('pk')) \
            .order_by('occurred_at').values_list('phone_token', 'masked_label', 'occurred_at', 'channel'):
        first.setdefault(token, (label, at, channel))
    rows = []
    for token in ordered:
        label, at, channel = first[token]
        why = f'On your list since {facts.on_list[token]:%-d %b %Y}' if col == 'internal' else WHY[col]
        rows.append({'number': label, 'firstContact': f'{at:%-d %b %Y}', 'channel': 'Text' if channel == 'sms' else 'Call', 'why': why})
    return {'source': name, 'column': col, 'total': len(missed), 'words': span.words, 'rows': rows}
