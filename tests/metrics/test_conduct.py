"""Card coverage, batch 3: Contact Conduct from real contacts (draft calling hours and limits, said so)."""
from datetime import UTC, datetime, timedelta

import pytest

from apps.consent.models import ConsentNeed, ConsentResult
from apps.contacts.models import ContactEvent
from apps.metrics.conduct import conduct_metrics, conduct_page
from apps.rulebook.loader import RULEBOOK_DIR, load
from tests.regulatory.test_portal_api import browser_for

pytestmark = pytest.mark.django_db
SEP = '2026-09'
n = iter(range(10**6))


@pytest.fixture(autouse=True)
def rulebook():
    load(RULEBOOK_DIR / 'v3.0.yaml')


def call(company, at, state='CA', zones=('America/Los_Angeles',), confidence='medium', person=None, **extra):
    i = next(n)
    return ContactEvent.objects.create(client=company, phone_token=person or f'p{i}', phone_token_kid='k1', source_system='convoso',
                                       source_record_id=f'c{i}', source_grade='C', channel=extra.pop('channel', 'call'), direction='outbound',
                                       occurred_at=at, recipient_state=state, time_zones=list(zones), location_confidence=confidence, **extra)


def metric(company, code):
    return next(m for m in conduct_metrics(company, SEP) if m['code'] == code)


def test_out_of_hours_counts_federal_and_state_and_possible(company):
    call(company, datetime(2026, 9, 10, 18, tzinfo=UTC))  # 11am Pacific: fine
    call(company, datetime(2026, 9, 10, 14, tzinfo=UTC))  # 7am Pacific: outside
    call(company, datetime(2026, 9, 10, 12, tzinfo=UTC), state='FL', zones=('America/New_York', 'America/Chicago'))  # 7am Chicago, two zones: possible
    m = metric(company, 'M16')
    assert m['value'] == 1 and m['display'] == '1 · 1'  # one call, outside both windows and '1 possible' in m['note'] and 'not confirmed by a lawyer' in m['note']
    page = conduct_page(company, SEP)
    assert page['byState'] == [{'state': 'California', 'count': 1, 'window': '8am – 9pm'}] and page['possibleLocationUncertain'] == 1
    assert {h['hour']: h['outside'] for h in page['hoursOfDay']} == {'7': True, '8': False, '11': False}


def test_a_verified_contact_is_not_a_federal_solicitation(company):
    c = call(company, datetime(2026, 9, 10, 14, tzinfo=UTC))
    ConsentNeed.objects.create(client=company, contact=c, variant='strict', category='marketing', robocall=False, bases=[], is_legal_basis=False, rulebook_version='3.0')
    ConsentResult.objects.create(client=company, contact=c, variant='strict', status='verified', evaluation_as_of=c.occurred_at, rulebook_version='3.0')
    assert metric(company, 'M16')['display'] == '0 · 1'


def test_over_the_florida_limit(company):
    for hour in (13, 16, 19, 22):  # four calls in a day, limit 3 per 24 h (draft)
        call(company, datetime(2026, 9, 10, hour, tzinfo=UTC), state='FL', zones=('America/New_York',), person='same')
    assert metric(company, 'M17')['value'] == 1


def test_holidays_wait_for_the_rule_and_caller_id_waits_for_test_dials(company):
    assert metric(company, 'M18')['notMeasured'].startswith('Rule pending')
    assert 'Module 9' in metric(company, 'M21')['notMeasured']


def test_cross_border_and_abandoned_calls(company):
    call(company, datetime(2026, 9, 10, 18, tzinfo=UTC), is_non_us=True, country='CA')
    for i in range(20):
        call(company, datetime(2026, 9, 11, 18, tzinfo=UTC), answered=True, campaign='SP-Roof', disposition='ABANDON' if i < 2 else 'SALE')
    assert metric(company, 'M15')['value'] == 1
    assert metric(company, 'M31')['value'] == 10.0
    assert conduct_page(company, SEP)['byCampaign'] == [{'campaign': 'SP-Roof', 'rate': 10.0}]


def test_robo_contacts_without_the_needed_proof(company):
    c = call(company, datetime(2026, 9, 10, 18, tzinfo=UTC), dial_mode='')
    ConsentNeed.objects.create(client=company, contact=c, variant='strict', category='marketing', robocall=True, bases=[], is_legal_basis=True, rulebook_version='3.0')
    ConsentResult.objects.create(client=company, contact=c, variant='strict', status='no_proof', evaluation_as_of=c.occurred_at, rulebook_version='3.0')
    m = metric(company, 'M19')
    assert m['value'] == 1 and '1 with dial mode unknown' in m['note']


def test_history_and_the_api(company, member_user):
    call(company, datetime(2026, 8, 10, 14, tzinfo=UTC))
    call(company, datetime(2026, 9, 10, 14, tzinfo=UTC))
    api = browser_for(member_user)
    m16 = next(m for m in api.get('/api/metrics?period=2026-09').json() if m['code'] == 'M16')
    assert m16['history'][-2:] == [1, 1]
    assert api.get('/api/conduct').json()['metrics'][0] == 'M16'
