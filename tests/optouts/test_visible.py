"""Made visible: the number page's real seal, the Opt-outs card from the STOP list, and the two admin record pages."""
import json
from datetime import UTC, date, datetime, timedelta
from unittest import mock

import pytest

from apps.anchoring import stamps
from apps.anchoring.seal import seal_finished_days
from apps.connections.models import Connection, Status
from apps.contacts.normalize import normalize_record
from apps.ledger.models import Fingerprint, PurgeLog
from apps.ledger.record import ledger_job
from apps.optouts.models import OptOutEvent
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.staff.models import StaffUser
from apps.sync.connectors import convoso as cv
from apps.sync.models import SyncGap
from tests.conftest import PASSWORD
from tests.regulatory.test_portal_api import browser_for

pytestmark = pytest.mark.django_db
DAY = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)


@pytest.fixture
def setup(company, member_user, monkeypatch):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    company.start_date = date(2026, 10, 1)
    company.save()
    conn = Connection(client=company, provider='convoso', status=Status.CONNECTED)
    conn.set_credentials({'key': 'k', 'secret': 'America/New_York'})
    conn.save()
    monkeypatch.setattr(stamps, 'tsa_stamp', lambda root: ('https://tsa.test', b'signed', DAY))
    monkeypatch.setattr(stamps, 'ots_stamp', lambda root: ('https://ots.test', b'pending'))
    return conn, browser_for(member_user)


def call(company, conn, n, when):
    record = cv.Convoso(conn).record({'id': str(n), 'phone_number': '9165550001', 'status': 'NI', 'call_date': when})
    with ledger_job(company, 'convoso poll') as job:
        job.record(source_system='convoso', source_record_id=record.source_record_id, raw=record.raw, content_kind='call', source_grade='C')
    normalize_record(company, conn, record, [])
    return record


def test_number_page_shows_the_real_seal(company, setup):
    conn, api = setup
    call(company, conn, 1, '2026-10-01 11:00:00')
    ref = api.get('/api/contacts').json()[0]['phoneE164']
    assert api.get(f'/api/evidence/{ref}').json()['anchor']['anchored'] is False  # read today: sealed tonight
    Fingerprint.objects.update(fetched_at=DAY)
    seal_finished_days()
    seal = api.get(f'/api/evidence/{ref}').json()['anchor']
    assert seal['anchored'] and seal['date'] == '2026-10-01' and len(seal['root']) == 64 and seal['stamped']
    assert (seal['sealedCount'], seal['recordCount']) == (1, 1)


def test_opt_outs_card_lists_the_stop_list_with_deadline_and_contacts_after(company, setup):
    conn, api = setup
    call(company, conn, 1, '2026-10-01 11:00:00')
    token = company.contacts.get().phone_token
    OptOutEvent.objects.create(client=company, phone_token=token, at=DAY + timedelta(hours=1), channel='text', method='keyword',
                               keyword='STOP', source_system='twilio', source_record_id='SM1')
    call(company, conn, 2, '2026-10-03 11:00:00')  # contacted again after the STOP
    with mock.patch('apps.optouts.api.timezone.now', return_value=datetime(2026, 10, 5, 12, tzinfo=UTC)):
        rows = api.get('/api/optouts').json()
    assert len(rows) == 1
    r = rows[0]
    assert (r['phoneDisplay'], r['how'], r['words'], r['deadline']) == ('(916) •••-0001', 'Text · keyword', 'STOP', '2026-10-16')
    assert r['businessDaysLeft'] == 8 and r['deadlineProvisional'] and r['dialerMarked'] is None  # Columbus Day skipped
    assert r['contactsAfter']['count'] == 1 and r['contactsAfter']['afterDeadline'] is False


def test_another_company_sees_no_opt_outs(company, setup, other_admin):
    OptOutEvent.objects.create(client=company, phone_token='x', at=DAY, channel='text', method='keyword', keyword='STOP',
                               source_system='twilio', source_record_id='SM1')
    assert browser_for(other_admin).get('/api/optouts').json() == []


def test_admin_shows_cleanups_and_missed_records(client, company):
    PurgeLog.objects.create(client=company, job_id='00000000-0000-0000-0000-000000000001', job_name='five9 poll', rows_removed=214, reason='TimeoutError')
    SyncGap.objects.create(client=company, source_system='twilio', source_record_id='SM9', sha256='0' * 64, found_by='catchup',
                           changed_at=DAY, delay_seconds=4200)
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    cleanups = client.get('/civ-admin/ledger/purgelog/').content.decode()
    assert 'five9 poll' in cleanups and '214' in cleanups and 'TimeoutError' in cleanups
    missed = client.get('/civ-admin/sync/syncgap/').content.decode()
    assert 'SM9' in missed and '1 h 10 min' in missed
    assert client.get('/civ-admin/ledger/purgelog/add/').status_code == 403
    menu = client.get('/civ-admin/').content.decode()
    assert 'Failed-job cleanups' in menu and 'Missed records' in menu
