"""Module 10 step 4: Exposure = min(100, D × Venue × Targeting × Volume) and its grade (Exposure Indicator v2.2: A under
25 · B 25–39 · C 40–48 · D 49–66 · F 67+). Owner decisions 2026-10-21 (draft values in the Rulebook,
`exposure_multipliers`):
- Venue from the states of the people contacted: states where people can sue under their own calling law; 10 %+ of
  contacts into FL / OK / WA / TX / CT counts as heavy (1.30);
- Volume from the real contacts of the 12 months to the month's end; 1.30 only above 1M with both calls and texts;
- Targeting 1.00 until lawsuit data exists (step 4b);
- caps that hold the grade at C or worse: the hard cap (legal-basis contacts with no proof above hard_cap_share; rule
  pending while that value is TBD) and the coverage cap (M36 below 60 %, Module 14)."""
from datetime import timedelta

from apps.consent.models import ConsentResult
from apps.contacts.models import ContactEvent
from apps.rulebook.lookup import NoRulebook, RulePending, RuleSet

DRAFT = {'venue_states': ['FL', 'OK', 'MD', 'WA', 'TX', 'CT', 'VA', 'GA', 'NJ', 'UT', 'IN', 'MS', 'KY'],
         'venue_heavy_states': ['FL', 'OK', 'WA', 'TX', 'CT'], 'venue_heavy_share': 0.1, 'venue_bands': [[0, 1.0], [2, 1.1], [5, 1.2]],
         'venue_top': 1.3, 'venue_cap': 1.35, 'volume_bands': [[100000, 0.9], [500000, 1.0], [1000000, 1.1]], 'volume_top': 1.2,
         'volume_top_multichannel': 1.3, 'volume_cap': 1.35, 'targeting_cap': 1.5}
GRADES = [(25, 'A'), (40, 'B'), (49, 'C'), (67, 'D')]
ORDER = 'ABCDF'


def settings(on) -> dict:
    try:
        found = RuleSet().get('exposure_multipliers', on=on).value
    except (NoRulebook, KeyError, LookupError):
        found = None
    return {**DRAFT, **(found or {})}


def grade(x: float) -> str:
    return next((g for limit, g in GRADES if x < limit), 'F')


def venue(contacts, s: dict) -> dict:
    states = list(contacts.exclude(recipient_state='').values_list('recipient_state', flat=True))
    reached = sorted(set(states) & set(s['venue_states']))
    heavy = sorted(st for st in s['venue_heavy_states'] if states and states.count(st) / len(states) >= s['venue_heavy_share'])
    if heavy or len(reached) > s['venue_bands'][-1][0]:
        value = s['venue_top']
    else:
        value = next(v for limit, v in s['venue_bands'] if len(reached) <= limit)
    return {'value': min(value, s['venue_cap']), 'states': reached, 'heavy': heavy}


def volume(client, end, s: dict) -> dict:
    year = ContactEvent.objects.filter(client=client, direction='outbound', is_primary=True, is_test=False,
                                       occurred_at__gte=end - timedelta(days=365), occurred_at__lt=end)
    n = year.count()
    both = year.filter(channel='call').exists() and year.filter(channel='text').exists()
    top = s['volume_bands'][-1][0]
    if n > top:
        value = s['volume_top_multichannel'] if both else s['volume_top']
    else:
        value = next(v for limit, v in s['volume_bands'] if n <= limit)
    return {'value': min(value, s['volume_cap']), 'contactsPerYear': n, 'callsAndTexts': both}


def hard_cap(client, start, end, on) -> dict:
    try:
        share = RuleSet().get('hard_cap_share', on=on).require()
    except (NoRulebook, KeyError, LookupError, RulePending):
        return {'state': 'rule_pending'}
    rows = ConsentResult.objects.filter(client=client, variant='strict', frozen=False, is_legal_basis=True, contact__is_primary=True,
                                        contact__occurred_at__gte=start, contact__occurred_at__lt=end).exclude(status__in=['pending', 'not_needed'])
    total = rows.count()
    if not total:
        return {'state': 'not_measured'}
    bad = rows.filter(status__in=['no_proof', 'conflicting']).count() / total
    return {'state': 'held' if bad > float(share) else 'clear', 'share': round(bad, 4)}


def exposure(client, start, end, contacts, defect: float | None, on, coverage_cap: dict | None = None) -> dict:
    s = settings(on)
    v, vol = venue(contacts, s), volume(client, end, s)
    t = {'value': 1.0, 'note': 'No lawsuit data yet'}
    caps = {'hard': hard_cap(client, start, end, on), 'coverage': coverage_cap or {'state': 'not_measured'}}  # coverage: M36 (Module 14)
    if defect is None:
        return {'venue': v, 'targeting': t, 'volume': vol, 'caps': caps, 'value': None, 'grade': None}
    raw = defect * v['value'] * t['value'] * vol['value']
    value = round(min(100.0, raw), 1)
    g = grade(value)
    held = [k for k, c in caps.items() if c['state'] == 'held']
    if held and ORDER.index(g) < ORDER.index('C'):
        g = 'C'
    return {'venue': v, 'targeting': t, 'volume': vol, 'caps': caps, 'value': value, 'raw': round(raw, 1), 'clamped': raw > 100,
            'grade': g, **({'heldBy': held} if held else {})}
