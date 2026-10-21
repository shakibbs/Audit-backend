"""Module 10 step 1: each month's metrics saved nightly; locked 5 days after the month ends; a locked month is never
overwritten — a change makes a new, revised version; the month list runs from the client's start date."""
from datetime import UTC, date, datetime, timedelta

import pytest

from apps.contacts.models import ContactEvent
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.scoring.models import MetricSnapshot, SnapshotRun
from apps.scoring.snapshots import months, periods, run_nightly, saved_metrics, snapshot

pytestmark = pytest.mark.django_db
SEP = date(2026, 9, 1)
n = iter(range(10**6))


@pytest.fixture(autouse=True)
def rules():
    load(RULEBOOK_DIR / 'v3.0.yaml')


def at(day, hour=15):
    return datetime(2026, 9, day, hour, tzinfo=UTC)


def late_call(company, day):
    """A call at 11 pm New York time: outside calling hours (M16)."""
    ContactEvent.objects.create(client=company, phone_token=f'p{next(n)}', phone_token_kid='k1', source_system='vicidial', source_record_id=f'c{next(n)}',
                                source_grade='B', channel='call', direction='outbound', occurred_at=at(day, 3), time_zones=['America/New_York'])


def test_month_list_runs_from_the_start_date_newest_first(company):
    assert [m.isoformat() for m in months(company, date(2026, 10, 21))] == ['2026-10-01', '2026-09-01', '2026-08-01', '2026-07-01', '2026-06-01']


def test_open_month_is_saved_and_replaced_not_versioned(company):
    snapshot(company, SEP, now=at(20))
    snapshot(company, SEP, now=at(21))
    run = SnapshotRun.objects.get()
    assert (run.version, run.locked, run.revised) == (1, False, False)
    assert {m.code for m in run.metrics.all()} >= {'M01', 'M10', 'M16', 'M08', 'M09', 'M38'}
    assert MetricSnapshot.objects.get(run=run, code='M38').state == 'not_measured'


def test_locked_five_days_after_the_month(company):
    assert not snapshot(company, SEP, now=datetime(2026, 10, 5, 4, tzinfo=UTC)).locked
    assert snapshot(company, SEP, now=datetime(2026, 10, 6, 4, tzinfo=UTC)).locked
    assert snapshot(company, SEP, now=datetime(2026, 10, 7, 4, tzinfo=UTC)) is None  # locked: left alone on normal nights


def test_a_locked_month_is_never_overwritten_a_change_makes_a_revised_version(company):
    snapshot(company, SEP, now=datetime(2026, 10, 6, 4, tzinfo=UTC))
    assert snapshot(company, SEP, now=datetime(2026, 10, 11, 4, tzinfo=UTC), recheck_locked=True) is None  # nothing changed
    late_call(company, 12)  # late record
    new = snapshot(company, SEP, now=datetime(2026, 10, 18, 4, tzinfo=UTC), recheck_locked=True)
    assert (new.version, new.revised) == (2, True)
    assert SnapshotRun.objects.filter(period=SEP).count() == 2  # the first version is kept
    assert periods(company)[1] == {'id': '2026-09', 'label': 'Sep 2026', 'revisedOn': '2026-10-18'}


def test_nightly_run_saves_every_month_once_and_rechecks_on_sundays(company):
    saturday = datetime(2026, 10, 17, 4, tzinfo=UTC)
    assert run_nightly(company, saturday) == 5  # Jun–Oct, all saved the first night
    assert run_nightly(company, saturday + timedelta(hours=1)) == 1  # only October is still open
    assert run_nightly(company, saturday + timedelta(days=1)) == 1  # Sunday: locked months re-checked, nothing changed


def test_saved_month_is_what_the_api_sends_with_history(company, member_user, signed_in):
    late_call(company, 3)
    snapshot(company, SEP, now=datetime(2026, 10, 6, 4, tzinfo=UTC))
    saved = {m['code']: m for m in saved_metrics(company, '2026-09')}
    assert saved['M16']['value'] == 1 and saved['M16']['history'][-1] == 1 and len(saved['M16']['history']) == 4
    api = signed_in(member_user)
    assert {m['code']: m['value'] for m in api.get('/api/metrics?period=2026-09').json()}['M16'] == 1
    session = api.get('/api/session').json()
    assert session['periods'][0]['id'] == datetime.now(UTC).strftime('%Y-%m') and session['periods'][-1] == {'id': '2026-06', 'label': 'Jun 2026'}
