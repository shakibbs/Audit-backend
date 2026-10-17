"""Records completeness (M37): what CiV read against the bill; days present; STOP replies; "not available" is left out."""
import io
import json
import urllib.parse
from datetime import UTC, date, datetime, timedelta

import pytest

from apps.connections.models import Connection, Status
from apps.contacts.models import ContactEvent
from apps.optouts.models import OptOutEvent
from apps.reconcile import billing
from apps.reconcile.check import check_month
from apps.reconcile.models import PeriodIntegrity, Reconciliation
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.tenancy.scope import _scope

pytestmark = pytest.mark.django_db
SEP = date(2026, 9, 1)
WORKING_DAYS_SEP = [d for d in (SEP + timedelta(days=i) for i in range(30)) if d.weekday() < 5 and d != date(2026, 9, 7)]


@pytest.fixture(autouse=True)
def rulebook(db):
    load(RULEBOOK_DIR / 'v3.0.yaml')


def twilio(client):
    c = Connection(client=client, provider='twilio', status=Status.CONNECTED)
    c.set_credentials({'account': 'AC1', 'key': 'k'})
    c.save()
    return c


def texts(client, n, days=WORKING_DAYS_SEP, direction='outbound', source='twilio', channel='text'):
    for i in range(n):
        day = days[i % len(days)]
        ContactEvent.objects.create(client=client, phone_token=f'p{i}', phone_token_kid='k1', source_system=source, source_record_id=f'{source}{channel}{i}',
                                    source_grade='C', channel=channel, direction=direction, occurred_at=datetime(day.year, day.month, day.day, 15, tzinfo=UTC))


def billed(monkeypatch, texts_billed, calls_billed=0):
    monkeypatch.setattr(billing, 'twilio_billed', lambda conn, measure, start, end: texts_billed if measure == 'texts' else calls_billed)


def row(client, measure):
    return Reconciliation.objects.get(client=client, period=SEP, measure=measure)


def test_91_percent_is_complete(company, monkeypatch):
    twilio(company)
    texts(company, 912)
    billed(monkeypatch, 1000)
    month = check_month(company, SEP)
    assert row(company, 'texts').ratio == pytest.approx(0.912) and not month.incomplete and month.completeness == pytest.approx(0.912)
    assert row(company, 'calls').available is False  # nothing billed for calls: left out, not failed


def test_70_percent_marks_the_month_incomplete(company, monkeypatch):
    twilio(company)
    texts(company, 700)
    billed(monkeypatch, 1000)
    month = check_month(company, SEP)
    assert month.incomplete and month.completeness == pytest.approx(0.7) and 'texts' in month.flagged_by


def test_lowest_of_calls_and_texts_is_m37(company, monkeypatch):
    twilio(company)
    texts(company, 950)
    texts(company, 80, channel='call')
    billed(monkeypatch, 1000, calls_billed=100)
    assert check_month(company, SEP).completeness == pytest.approx(0.8)


def test_a_dialer_without_a_bill_is_checked_by_its_own_total(company, monkeypatch):
    from apps.sync.connectors.convoso import Convoso
    monkeypatch.setattr(Convoso, 'count_between', lambda self, measure, start, end: 50)
    Connection.objects.create(client=company, provider='convoso', status=Status.CONNECTED)
    texts(company, 48, source='convoso', channel='call')
    month = check_month(company, SEP)
    calls = Reconciliation.objects.get(client=company, period=SEP, measure='calls', source_system='convoso')
    assert (calls.method, calls.records, calls.independent_total) == ('tool_total', 48, 50)
    assert month.completeness == pytest.approx(0.96) and not month.incomplete


def test_when_the_total_cannot_be_read_the_volume_pattern_stands_in(company, monkeypatch):
    from apps.sync.connectors.convoso import Convoso

    def broken(self, measure, start, end):
        raise TimeoutError
    monkeypatch.setattr(Convoso, 'count_between', broken)
    Connection.objects.create(client=company, provider='convoso', status=Status.CONNECTED)
    texts(company, 50, days=WORKING_DAYS_SEP[:15], source='convoso', channel='call')  # 15 of 21 working days
    month = check_month(company, SEP)
    calls = Reconciliation.objects.get(client=company, period=SEP, measure='calls', source_system='convoso')
    assert (calls.method, calls.records, calls.independent_total) == ('volume', 15, 21) and 'TimeoutError' in calls.note
    assert calls.flagged and month.incomplete and month.completeness == pytest.approx(15 / 21)


def test_a_sudden_drop_is_flagged(company, monkeypatch):
    from apps.sync.connectors.convoso import Convoso

    def broken(self, measure, start, end):
        raise TimeoutError
    monkeypatch.setattr(Convoso, 'count_between', broken)
    Connection.objects.create(client=company, provider='convoso', status=Status.CONNECTED)
    texts(company, 2000, days=[d for d in WORKING_DAYS_SEP if d.day <= 22], source='convoso', channel='call')
    for i, day in enumerate(d for d in WORKING_DAYS_SEP if d.day > 23):  # then almost nothing
        ContactEvent.objects.create(client=company, phone_token=f'late{i}', phone_token_kid='k1', source_system='convoso', source_record_id=f'late{i}',
                                    source_grade='C', channel='call', direction='outbound', occurred_at=datetime(day.year, day.month, day.day, 15, tzinfo=UTC))
    check_month(company, SEP)
    calls = Reconciliation.objects.get(client=company, period=SEP, measure='calls', source_system='convoso')
    assert calls.flagged


def test_every_tool_counts_and_the_lowest_wins(company, monkeypatch):
    from apps.imports.models import CrmCreation
    from apps.sync.connectors.convoso import Convoso
    from apps.sync.connectors.salesforce import Salesforce
    monkeypatch.setattr(Convoso, 'count_between', lambda self, measure, start, end: 100)
    monkeypatch.setattr(Salesforce, 'count_between', lambda self, measure, start, end: 10)
    billed(monkeypatch, 100)
    twilio(company)
    texts(company, 99)
    Connection.objects.create(client=company, provider='convoso', status=Status.CONNECTED)
    texts(company, 100, source='convoso', channel='call')
    Connection.objects.create(client=company, provider='salesforce', status=Status.CONNECTED)
    for n in range(8):
        CrmCreation.objects.create(client=company, source_system='salesforce', record_id=f'leads:{n}', created_at=datetime(2026, 9, 10, tzinfo=UTC))
    month = check_month(company, SEP)
    methods = dict(Reconciliation.objects.filter(client=company, period=SEP, measure__in=['texts', 'calls', 'crm_records'],
                                                 available=True).values_list('source_system', 'method'))
    assert methods == {'twilio': 'bill', 'convoso': 'tool_total', 'salesforce': 'tool_total'}
    assert month.completeness == pytest.approx(0.8) and month.incomplete and 'crm_records' in month.flagged_by


def test_a_tool_civ_cannot_read_yet_is_not_available_never_failed(company):
    Connection.objects.create(client=company, provider='aircall', status=Status.CONNECTED)
    month = check_month(company, SEP)
    calls = Reconciliation.objects.get(client=company, period=SEP, measure='calls', source_system='aircall')
    assert not calls.available and 'cannot read' in calls.note and month.completeness is None


def test_missing_days_are_flagged_but_not_part_of_m37(company, monkeypatch):
    twilio(company)
    texts(company, 900, days=WORKING_DAYS_SEP[:18])  # 18 of 21 working days
    billed(monkeypatch, 950)
    month = check_month(company, SEP)
    days = row(company, 'days_present')
    assert (days.records, days.independent_total, days.flagged) == (18, 21, True)
    assert month.completeness == pytest.approx(900 / 950) and not month.incomplete and 'days_present' in month.flagged_by


def test_many_texts_and_no_stop_replies_is_suspicious(company, monkeypatch):
    twilio(company)
    texts(company, 1500)
    billed(monkeypatch, 1500)
    check_month(company, SEP)
    assert row(company, 'stop_replies').flagged and '1,500 texts' in row(company, 'stop_replies').note
    OptOutEvent.objects.create(client=company, phone_token='p1', at=datetime(2026, 9, 9, tzinfo=UTC), channel='text', method='keyword',
                               keyword='STOP', source_system='twilio', source_record_id='SMx')
    check_month(company, SEP)
    assert not row(company, 'stop_replies').flagged


def test_above_100_percent_is_listed_for_review(company, monkeypatch):
    twilio(company)
    texts(company, 1100)
    billed(monkeypatch, 1000)
    check_month(company, SEP)
    assert row(company, 'texts').ratio == pytest.approx(1.1) and 'review' in row(company, 'texts').note


def test_volume_counts_each_contact_once(company, monkeypatch):
    twilio(company)
    texts(company, 10)
    ContactEvent.objects.filter(source_record_id='twiliotext0').update(is_primary=False)
    billed(monkeypatch, 10)
    assert check_month(company, SEP).contacts == 9


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_twilio_usage_request(company, monkeypatch):
    conn = twilio(company)
    pages = [{'usage_records': [{'count': '600', 'category': 'sms-outbound'}], 'next_page_uri': '/2010-04-01/Accounts/AC1/Usage/Records/Daily.json?Page=1'},
             {'usage_records': [{'count': '400', 'category': 'sms-outbound'}], 'next_page_uri': None}]
    asked = []

    def urlopen(request, timeout):
        asked.append(request.full_url)
        return Reply(json.dumps(pages[len(asked) - 1]).encode())
    monkeypatch.setattr(billing.urllib.request, 'urlopen', urlopen)
    assert billing.twilio_billed(conn, 'texts', SEP, date(2026, 9, 30)) == 1000
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(asked[0]).query))
    assert '/Usage/Records/Daily.json' in asked[0] and query['Category'] == 'sms-outbound' and query['StartDate'] == '2026-09-01'


def test_checks_are_locked_per_client(company, other_company, monkeypatch):
    billed(monkeypatch, 10)
    for client in (company, other_company):
        twilio(client)
        texts(client, 10)
        check_month(client, SEP)
    with _scope('client', str(company.pk)):
        assert set(PeriodIntegrity.objects.values_list('client_id', flat=True)) == {company.pk}
