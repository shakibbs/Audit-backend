"""Contact Conduct (spec metrics M15–M21, M31) from the contacts CiV already holds. Calling hours, frequency limits and
holiday rules are still TBD in the Rulebook: like the calling window (Module 4), the draft values are used and every
number says so ("draft hours, not confirmed by a lawyer"). A rule with no draft at all → "rule pending".

Window: the selected month, or the last metric_window_days (30) when none is chosen. Outbound, counted (not copies),
not CiV's test numbers. Each contact is checked in every time zone its number could be in; a low-confidence location
is a "possible" case, never counted as confirmed."""
from collections import Counter, defaultdict
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.consent.models import ConsentNeed, ConsentResult
from apps.contacts.calling import _allowed, _hours
from apps.contacts.models import ContactEvent
from apps.rulebook.lookup import NoRulebook, RuleSet

CONDUCT = ['M16', 'M17', 'M18', 'M31', 'M19', 'M20', 'M21', 'M15']
DRAFT = 'draft hours, not confirmed by a lawyer'
ABANDON_WORDS = ('abandon', 'drop', 'abnd')  # dialer result codes that mean "answered, no agent came on" (rough until mapped)
STATES = {'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut',
          'DE': 'Delaware', 'DC': 'District of Columbia', 'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois',
          'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
          'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi', 'MO': 'Missouri', 'MT': 'Montana',
          'NE': 'Nebraska', 'NV': 'Nevada', 'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
          'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania',
          'RI': 'Rhode Island', 'SC': 'South Carolina', 'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
          'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming',
          'PR': 'Puerto Rico'}


def span(period: str | None, today=None) -> tuple[datetime, datetime]:
    """'2026-09' → that calendar month; nothing → the last 30 days."""
    if period:
        first = datetime.strptime(period, '%Y-%m').replace(tzinfo=UTC)
        nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        return first, nxt
    end = timezone.now()
    return end - timedelta(days=30), end


def months_before(period: str | None, n: int) -> list[str]:
    first = datetime.strptime(period, '%Y-%m') if period else timezone.now().replace(day=1)
    out = []
    for _ in range(n):
        first = (first.replace(day=1) - timedelta(days=1)).replace(day=1)
        out.insert(0, first.strftime('%Y-%m'))
    return out


def contacts(client, start, end):
    return ContactEvent.objects.filter(client=client, direction='outbound', is_primary=True, is_test=False,
                                       occurred_at__gte=start, occurred_at__lt=end)


class Rules:
    """The draft rule values, read once per state for a run."""
    def __init__(self, on):
        try:
            self.rules = RuleSet('draft')
        except NoRulebook:
            self.rules = None
        self.on, self.cache = on, {}

    def get(self, key: str, state: str):
        if self.rules is None:
            return None
        if (key, state) not in self.cache:
            try:
                rule = self.rules.get(key, on=self.on, state=state or None)
                self.cache[(key, state)] = rule.value
            except Exception:
                self.cache[(key, state)] = None
        return self.cache[(key, state)]


def outside(c, value: dict) -> bool:
    """Outside the window in any time zone the person could be in (the stricter result counts)."""
    return any(not _allowed(c.occurred_at.astimezone(ZoneInfo(z)), value) for z in (c.time_zones or []))


def hours_check(client, start, end) -> dict:
    """M16 and the hour / state charts."""
    rules = Rules(start.date())
    federal_value = rules.get('calling_hours', '')
    verified = set(ConsentResult.objects.filter(client=client, variant='strict', status__in=['verified', 'weak'],
                                                contact__occurred_at__gte=start, contact__occurred_at__lt=end).values_list('contact_id', flat=True))
    federal = state = possible = either = 0  # either: each contact once, however many windows it broke
    by_state, windows, hours = Counter(), {}, Counter()
    for c in contacts(client, start, end).exclude(is_non_us=True).only('occurred_at', 'time_zones', 'recipient_state', 'location_confidence'):
        if c.time_zones:
            hours[c.occurred_at.astimezone(ZoneInfo(c.time_zones[0])).hour] += 1
        value = rules.get('calling_hours', c.recipient_state)
        if not value or not c.time_zones:
            continue
        out_state = outside(c, value)
        out_federal = bool(federal_value) and outside(c, federal_value) and c.pk not in verified
        if not (out_state or out_federal):
            continue
        if c.location_confidence == 'low' or len(c.time_zones) > 1:
            possible += 1
            continue
        federal += out_federal
        either += 1
        if out_state:
            state += 1
            name = STATES.get(c.recipient_state, c.recipient_state or 'Unknown')
            by_state[name] += 1
            windows[name] = _hours(value)
    measured = federal_value is not None
    metric = {'code': 'M16', 'value': either if measured else None, 'display': f'{federal:,} · {state:,}',
              'note': f'Federal · state; {possible:,} possible (location uncertain) · {DRAFT}',
              'notMeasured': None if measured else 'Rule pending: calling hours not set yet (counsel item A6)'}
    chart = {'byState': [{'state': s, 'count': n, 'window': windows[s]} for s, n in by_state.most_common(10)],
             'possibleLocationUncertain': possible,
             'hoursOfDay': [{'hour': str(h), 'count': hours[h], 'outside': h < 8 or h >= 21} for h in sorted(hours)]}
    return {'metric': metric, 'chart': chart}


def frequency_check(client, start, end) -> dict:
    """M17: a person (number and owner) contacted more often than the state allows in its window (campaigns together)."""
    rules = Rules(start.date())
    rows = contacts(client, start - timedelta(days=7), end).exclude(is_non_us=True) \
        .values_list('phone_token', 'epoch_id', 'occurred_at', 'recipient_state', 'location_confidence')
    people = defaultdict(list)
    for token, epoch, at, state, confidence in rows:
        people[(token, epoch)].append((at, state, confidence))
    over = possible = 0
    any_limit = False
    for calls in people.values():
        calls.sort()
        for i, (at, state, confidence) in enumerate(calls):
            limit = rules.get('frequency_limits', state)
            if not isinstance(limit, dict) or at < start:
                continue
            any_limit = True
            window = timedelta(hours=limit.get('window_hours', 24))
            earlier = sum(1 for prev, _, _ in calls[:i] if at - window < prev)
            if earlier >= limit.get('max', 3):
                if confidence == 'low':
                    possible += 1
                else:
                    over += 1
    return {'code': 'M17', 'value': over, 'display': f'{over:,}',
            'note': f'{possible:,} possible (location uncertain) · draft limits, not confirmed by a lawyer' if any_limit
            else 'No contacts in a state with a frequency limit · draft limits, not confirmed by a lawyer', 'notMeasured': None}


def holiday_check(client, start, end) -> dict:
    """M18: no state holiday rule has even a draft value yet."""
    return {'code': 'M18', 'value': None, 'display': 'Not measured', 'note': 'Rule pending',
            'notMeasured': 'Rule pending: state holiday restrictions not set yet (counsel item A8)'}


def robo_check(client, start, end) -> dict:
    """M19: robocalls and robotexts (strict reading) without the proof their category needs."""
    ids = list(ConsentNeed.objects.filter(client=client, variant='strict', robocall=True, contact__direction='outbound',
                                          contact__is_primary=True, contact__occurred_at__gte=start, contact__occurred_at__lt=end)
               .values_list('contact_id', flat=True))
    if not ids:
        return {'code': 'M19', 'value': 0, 'display': '0', 'note': 'No robocalls or robotexts in the period', 'notMeasured': None}
    results = ConsentResult.objects.filter(contact_id__in=ids, variant='strict', frozen=False).exclude(status__in=['pending', 'not_needed'])
    lacking = results.exclude(status__in=['verified', 'weak'])
    unknown_mode = ContactEvent.objects.filter(pk__in=lacking.values('contact_id'), dial_mode='').count()
    n = lacking.count()
    return {'code': 'M19', 'value': n, 'display': f'{n:,}',
            'note': f'Of {len(ids):,} robo contacts; {unknown_mode:,} with dial mode unknown (counted as autodialed)', 'notMeasured': None}


def caller_id_check(client, start, end) -> dict:
    """M21: the pass rate needs CiV's test dials (Module 9); the STIR/SHAKEN mix is shown when the dialer gives it."""
    mix = Counter(contacts(client, start, end).filter(channel='call').exclude(stir_attestation='').values_list('stir_attestation', flat=True))
    total = sum(mix.values())
    note = (' · '.join(f'{100 * mix[k] / total:.0f}% {k}' for k in sorted(mix)) + ' attestation') if total else 'STIR/SHAKEN attestation not available from your dialer'
    return {'code': 'M21', 'value': None, 'display': 'Not measured', 'note': note,
            'notMeasured': 'Test dials of each caller ID come with Module 9'}


def cross_border(client, start, end) -> dict:
    """M15: contacts to numbers outside the US (Canada and the Caribbean included)."""
    rows = contacts(client, start, end).filter(is_non_us=True)
    n = rows.count()
    countries = Counter(rows.values_list('country', flat=True))
    return {'code': 'M15', 'value': n, 'display': f'{n:,}',
            'note': ', '.join(f'{c or "?"} {k}' for c, k in countries.most_common(3)) or 'None outside the United States', 'notMeasured': None}


def abandon_check(client, start, end) -> dict:
    """M31 and the campaign chart: answered calls whose result code says abandoned (rough until each dialer's codes are mapped)."""
    rules = Rules(start.date())
    limit = float(rules.get('abandoned_call_max_rate', '') or 0.03) * 100
    answered = contacts(client, start, end).filter(channel='call', answered=True)
    by_campaign, total, dropped = defaultdict(lambda: [0, 0]), 0, 0
    for campaign, disposition in answered.values_list('campaign', 'disposition'):
        gone = any(w in (disposition or '').lower() for w in ABANDON_WORDS)
        total, dropped = total + 1, dropped + gone
        by_campaign[campaign or 'No campaign'][0] += 1
        by_campaign[campaign or 'No campaign'][1] += gone
    if not total:
        return {'metric': {'code': 'M31', 'value': None, 'display': 'Not measured', 'note': '',
                           'notMeasured': 'Your dialer does not say which calls were answered'},
                'chart': {'byCampaign': [], 'abandonLimit': limit}}
    rates = {c: 100 * d / a for c, (a, d) in by_campaign.items()}
    over = sum(1 for r in rates.values() if r > limit)
    rate = round(100 * dropped / total, 1)
    return {'metric': {'code': 'M31', 'value': rate, 'display': f'{rate}%',
                       'note': f'{over} campaign(s) above the {limit:g}% limit · from your dialer result codes', 'notMeasured': None},
            'chart': {'byCampaign': [{'campaign': c, 'rate': round(r, 1)} for c, r in sorted(rates.items(), key=lambda kv: -kv[1])[:10]],
                      'abandonLimit': limit}}


def conduct_metrics(client, period: str | None) -> list[dict]:
    """The seven metrics with a four-month history (three earlier months and this one)."""
    def values(start, end):
        return {m['code']: m for m in (hours_check(client, start, end)['metric'], frequency_check(client, start, end), holiday_check(client, start, end),
                                       abandon_check(client, start, end)['metric'], robo_check(client, start, end),
                                       caller_id_check(client, start, end), cross_border(client, start, end))}
    now = values(*span(period))
    past = [values(*span(p)) for p in months_before(period, 3)]
    for code, metric in now.items():
        metric['history'] = [p[code]['value'] for p in past] + [metric['value']]
    return list(now.values())


def conduct_page(client, period: str | None) -> dict:
    start, end = span(period)
    hours, abandon = hours_check(client, start, end), abandon_check(client, start, end)
    return {'metrics': CONDUCT, **hours['chart'], **abandon['chart']}
