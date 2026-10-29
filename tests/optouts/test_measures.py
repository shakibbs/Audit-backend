"""Module 9 step 5: M08 and M09 from the client's real opt-outs (no test lines), using the tool checks of step 3."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.connections.models import Connection, Status
from apps.contacts.models import ContactEvent
from apps.optouts.measures import propagation_time, unprocessed
from apps.optouts.models import MarkCheck, OptOutEvent
from apps.rulebook.loader import RULEBOOK_DIR, load

pytestmark = pytest.mark.django_db
NOW = timezone.now()
n = iter(range(10**6))


@pytest.fixture(autouse=True)
def rules():
    load(RULEBOOK_DIR / 'v3.0.yaml')


def optout(company, days_ago, counts=True, token=None):
    return OptOutEvent.objects.create(client=company, phone_token=token or f'p{next(n)}', at=NOW - timedelta(days=days_ago), channel='text',
                                      method='keyword', source_system='twilio', source_record_id=f'r{next(n)}', counts=counts)


def check(company, event, hours=None, marked=True, missed=False, deadline_days=14):
    tool = Connection.objects.create(client=company, provider='vicidial', status=Status.CONNECTED, label=f't{next(n)}')
    return MarkCheck.objects.create(client=company, optout=event, connection=tool, marked=marked, checked_at=NOW, missed=missed,
                                    marked_at=event.at + timedelta(hours=hours) if hours is not None else None,
                                    deadline_at=event.at + timedelta(days=deadline_days))


def span():
    return NOW - timedelta(days=60), NOW + timedelta(days=1)


def test_nothing_checked_is_not_measured(company):
    optout(company, 5)
    assert propagation_time(company, *span())['display'] == 'Not measured'


def test_median_and_90th_percentile_of_the_slowest_tool(company):
    for hours in (1, 2, 3):
        event = optout(company, 30)
        check(company, event, hours)
        check(company, event, hours / 2)  # the faster tool doesn't decide
    slow = optout(company, 30)
    check(company, slow, None, marked=False, missed=True)  # never marked by the deadline
    m08 = propagation_time(company, *span())
    assert (m08['value'], m08['display']) == (2.5, '2.5 h')
    assert m08['note'] == 'Median of 4 opt-outs; 90th percentile NEVER' and m08['source'] == 'Measured from your real opt-outs'


def test_still_inside_the_deadline_is_not_decided_yet(company):
    event = optout(company, 1)
    check(company, event, None, marked=False)
    assert propagation_time(company, *span())['display'] == 'Not measured'


def test_ai_opt_outs_before_the_exam_are_left_out(company):
    check(company, optout(company, 30, counts=False), 1)
    assert propagation_time(company, *span())['value'] is None


def test_m09_counts_not_marked_and_contacted_after_the_deadline(company):
    late = optout(company, 40, token='late')
    check(company, late, None, marked=False, missed=True)
    called = optout(company, 40, token='called')
    check(company, called, 1)
    ContactEvent.objects.create(client=company, phone_token='called', phone_token_kid='k1', source_system='vicidial', source_record_id='c1',
                                source_grade='B', channel='call', direction='outbound', occurred_at=NOW - timedelta(days=2))
    check(company, optout(company, 40, token='fine'), 1)
    optout(company, 1, token='recent')  # deadline not passed: left out
    m09 = unprocessed(company, *span())
    assert (m09['display'], m09['m09a'], m09['m09b']) == ('1 · 1', 1, 1) and 'of 3 opt-outs past the deadline' in m09['note']


def test_m09_not_measured_before_any_deadline_passed(company):
    optout(company, 1)
    assert unprocessed(company, *span())['display'] == 'Not measured'


def test_the_revocation_page_and_list_follow_the_month(company, member_user, signed_in):
    """Owner, 2026-10-30: the month picker — opt-outs received in that month, measured as of now."""
    from apps.optouts.measures import revocation_page
    this = NOW.date().replace(day=1)
    last = (this - timedelta(days=1)).replace(day=1)
    days_into = (NOW.date() - this).days
    check(company, optout(company, days_into + 3), hours=5)  # last month, stopped later
    check(company, optout(company, 0), hours=2)  # this month
    page = revocation_page(company, period=f'{last:%Y-%m}')
    assert page['tests'] == 1 and page['windowLabel'] == last.strftime('%b %Y') and page['windowFrom'] == last.isoformat()
    assert revocation_page(company)['windowLabel'] is None  # no month: the last 90 days, as before
    api = signed_in(member_user)
    assert len(api.get(f'/api/optouts?period={last:%Y-%m}').json()) == 1 and len(api.get('/api/optouts').json()) == 2
    assert api.get(f'/api/revocation?period={this:%Y-%m}').json()['tests'] == 1
