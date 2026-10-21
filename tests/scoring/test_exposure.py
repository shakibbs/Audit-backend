"""Module 10 step 4: Exposure = min(100, D × Venue × Targeting × Volume), grades A–F, the draft multipliers, the
hard cap (rule pending while TBD) and the coverage cap (waits for M36)."""
from datetime import UTC, date, datetime

import pytest
from django.db.models import F

from apps.contacts.models import ContactEvent
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.rulebook.models import RulebookVersion, RuleValue
from apps.scoring.exposure import DRAFT, exposure, grade, venue, volume
from apps.scoring.snapshots import snapshot

pytestmark = pytest.mark.django_db
START, END = datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
n = iter(range(10**6))


@pytest.fixture(autouse=True)
def rules():
    load(RULEBOOK_DIR / 'v3.0.yaml')


def contact(company, state='', channel='call', day=3):
    return ContactEvent.objects.create(client=company, phone_token=f'p{next(n)}', phone_token_kid='k1', source_system='vicidial',
                                       source_record_id=f'c{next(n)}', source_grade='B', channel=channel, direction='outbound',
                                       occurred_at=datetime(2026, 9, day, 16, tzinfo=UTC), recipient_state=state, time_zones=['America/New_York'])


def sent(company):
    return ContactEvent.objects.filter(client=company, direction='outbound')


@pytest.mark.parametrize('x,g', [(0, 'A'), (24.9, 'A'), (25, 'B'), (39.9, 'B'), (40, 'C'), (48.9, 'C'), (49, 'D'), (66.9, 'D'), (67, 'F'), (100, 'F')])
def test_grade_bands(x, g):
    assert grade(x) == g


def test_venue_counts_states_where_people_can_sue(company):
    for st in ['CA'] * 30 + ['MD', 'VA', 'GA']:
        contact(company, st)
    assert venue(sent(company), DRAFT) == {'value': 1.2, 'states': ['GA', 'MD', 'VA'], 'heavy': []}


def test_heavy_florida_is_the_top_band(company):
    for st in ['CA'] * 8 + ['FL'] * 2:
        contact(company, st)
    v = venue(sent(company), DRAFT)
    assert v['value'] == 1.3 and v['heavy'] == ['FL']


def test_no_states_is_neutral(company):
    contact(company, 'CA')
    assert venue(sent(company), DRAFT)['value'] == 1.0


def test_volume_from_a_years_contacts(company):
    contact(company)
    assert volume(company, END, DRAFT) == {'value': 0.9, 'contactsPerYear': 1, 'callsAndTexts': False}
    big = {**DRAFT, 'volume_bands': [[0, 0.9], [1, 1.0], [2, 1.1]]}  # tiny bands to test the top
    contact(company, channel='text')
    contact(company)
    assert volume(company, END, big)['value'] == 1.3  # over the top, calls and texts


def test_exposure_multiplies_and_clamps(company):
    for st in ['FL'] * 5:
        contact(company, st)
    e = exposure(company, START, END, sent(company), 40.0, date(2026, 9, 1))  # 40 × 1.3 × 1.0 × 0.9 = 46.8
    assert (e['value'], e['grade'], e['targeting']['value']) == (46.8, 'C', 1.0)
    e = exposure(company, START, END, sent(company), 95.0, date(2026, 9, 1))  # 111.15 → 100
    assert (e['value'], e['clamped'], e['grade']) == (100.0, True, 'F')


def test_no_defect_means_no_exposure(company):
    e = exposure(company, START, END, sent(company), None, date(2026, 9, 1))
    assert e['value'] is None and e['grade'] is None


def test_hard_cap_is_rule_pending_while_tbd_and_holds_at_c_when_set(company):
    e = exposure(company, START, END, sent(company), 10.0, date(2026, 9, 1))
    assert e['caps']['hard']['state'] == 'rule_pending' and e['grade'] == 'A'
    assert e['caps']['coverage']['state'] == 'not_measured'
    from apps.consent.models import ConsentResult
    c = contact(company)
    ConsentResult.objects.create(client=company, contact=c, variant='strict', status='no_proof', is_legal_basis=True, evaluation_as_of=c.occurred_at, rulebook_version='3.0')
    RuleValue.objects.filter(key='hard_cap_share', jurisdiction='US').update(status='proposed', value=0.05)
    RulebookVersion.objects.update(revision=F('revision') + 1)  # a Rulebook edit (clears the cache)
    e = exposure(company, START, END, sent(company), 10.0, date(2026, 9, 1))
    assert e['caps']['hard'] == {'state': 'held', 'share': 1.0} and (e['grade'], e['heldBy']) == ('C', ['hard'])


def test_saved_month_has_the_exposure(company):
    contact(company, 'FL')
    run = snapshot(company, date(2026, 9, 1), now=datetime(2026, 9, 20, tzinfo=UTC))
    e = run.score['exposure']
    assert e['venue']['heavy'] == ['FL'] and e['grade'] in 'ABCDF' and e['volume']['contactsPerYear'] == 1
