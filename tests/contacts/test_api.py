"""Contact Ledger, number page and "Can I call now?" through the client API."""
from datetime import UTC, date, datetime
from unittest import mock

import pytest

from apps.connections.models import Connection, Status
from apps.contacts import calling
from apps.contacts.models import ContactEvent
from apps.contacts.normalize import mask, normalize_record
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.sync.connectors import convoso as cv
from tests.regulatory.test_portal_api import browser_for

pytestmark = pytest.mark.django_db


@pytest.fixture
def calls(company, member_user):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    company.start_date = date(2026, 10, 1)
    company.save()
    c = Connection(client=company, provider='convoso', status=Status.CONNECTED)
    c.set_credentials({'key': 'k', 'secret': 'America/New_York'})
    c.save()
    for n, (number, when) in enumerate([('9165550001', '2026-10-01 11:30:00'), ('8505550002', '2026-10-01 11:40:00'),
                                        ('4165550003', '2026-10-01 11:50:00')], 1):
        normalize_record(company, c, cv.Convoso(c).record({'id': str(n), 'phone_number': number, 'status': 'NI', 'call_date': when}), [])
    return browser_for(member_user)


def test_masked_label_keeps_only_area_code_and_last_4():
    assert mask('+19165550001') == '(916) •••-0001' and mask('+442079460958') == '+44 ••• 0958'


def test_ledger_rows_are_real_masked_and_not_yet_checked(calls):
    rows = calls.get('/api/contacts').json()
    assert [r['phoneDisplay'] for r in rows] == ['(416) •••-0003', '(850) •••-0002', '(916) •••-0001']  # newest first
    first = rows[2]
    assert first['status'] == 'NOT_CHECKED' and 'not checked yet' in first['reasonText'] and first['where'] == 'CA · Los Angeles'
    assert 'location unsure' in rows[1]['flags'] and 'outside the US' in rows[0]['flags']
    assert all('555' not in r['phoneDisplay'] and not r['phoneE164'].startswith('+') for r in rows)
    assert calls.get('/api/contacts?status=VERIFIED').json() == []


def test_find_a_number_without_storing_it(calls):
    assert [r['phoneDisplay'] for r in calls.get('/api/contacts?q=(916) 555-0001').json()] == ['(916) •••-0001']
    assert [r['phoneDisplay'] for r in calls.get('/api/contacts?q=0002').json()] == ['(850) •••-0002']
    assert calls.get('/api/contacts?q=(916) 555-9999').json() == []


def test_number_page_with_calling_window_and_owners(calls):
    ref = calls.get('/api/contacts?q=9165550001').json()[0]['phoneE164']
    sacramento_6pm = datetime(2026, 10, 1, 1, 0, tzinfo=UTC)  # 6pm Pacific
    with mock.patch.object(calling.timezone, 'now', return_value=sacramento_6pm):
        page = calls.get(f'/api/evidence/{ref}').json()
    assert page['phone'] == '(916) •••-0001' and len(page['contacts']) == 1 and page['epochs'][0]['number'] == 1
    w = page['callingWindow']
    assert (w['verdict'], w['hours'], w['draft']) == ('ok', '8am – 9pm', True) and 'not confirmed by a lawyer' in w['note']
    assert calls.get('/api/evidence/p-000000000000000000000000').status_code == 404
    assert calls.get('/api/evidence/+19165550001').status_code == 404  # never by the number itself


def test_another_company_cannot_open_the_number(calls, other_admin):
    ref = calls.get('/api/contacts').json()[0]['phoneE164']
    assert browser_for(other_admin).get(f'/api/evidence/{ref}').status_code == 404


def test_can_i_call_now_uses_the_strictest_zone_and_stores_nothing(calls):
    before = ContactEvent.objects.count()
    eight_twenty_pm_central = datetime(2026, 10, 2, 1, 20, tzinfo=UTC)  # 8:20pm Central = 9:20pm Eastern
    with mock.patch('apps.contacts.api.timezone.now', return_value=eight_twenty_pm_central), \
         mock.patch.object(calling.timezone, 'now', return_value=eight_twenty_pm_central):
        fl = calls.call('post', '/api/can-call', {'number': '(850) 555-0002'}).json()
        ca = calls.call('post', '/api/can-call', {'number': '916-555-0001'}).json()
        jm = calls.call('post', '/api/can-call', {'number': '+1 876 555 0001'}).json()
    assert fl['state'] == 'FL' and fl['verdict'] == 'not_safe' and fl['hours'] == '8am – 8pm' and 'stricter' in fl['note']
    assert ca['verdict'] == 'ok' and ca['zones'][0]['allowed']  # 6:20pm in California
    assert jm['verdict'] == 'unknown' and 'Outside the United States' in jm['note']
    assert calls.call('post', '/api/can-call', {'number': '12'}).status_code == 400
    assert ContactEvent.objects.count() == before
