"""Module 9 step 6: what the portal gets — the Revocation page from real opt-outs, the Opt-outs table's tool answers,
the Overview AI card, M08 / M09 metrics, and the Who You Contact checks M41, M42, M48 and M45."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.connections.models import Connection, Status
from apps.contacts.models import ContactEvent
from apps.conversations.models import ConversationReview
from apps.metrics.who import who_contact
from apps.optouts.models import MarkCheck, OptOutEvent
from apps.rulebook.loader import RULEBOOK_DIR, load

pytestmark = pytest.mark.django_db
NOW = timezone.now()
n = iter(range(10**6))


@pytest.fixture(autouse=True)
def rules():
    load(RULEBOOK_DIR / 'v3.0.yaml')


def optout(company, days_ago, token, method='keyword', channel='text', keyword='STOP'):
    return OptOutEvent.objects.create(client=company, phone_token=token, at=NOW - timedelta(days=days_ago), channel=channel, method=method,
                                      keyword=keyword, source_system='twilio', source_record_id=f'r{next(n)}')


def check(company, event, tool, hours=None, marked=True, missed=False, urgent=False):
    return MarkCheck.objects.create(client=company, optout=event, connection=tool, marked=marked, checked_at=NOW, missed=missed,
                                    marked_at=event.at + timedelta(hours=hours) if hours is not None else None,
                                    urgent_at=NOW if urgent else None, deadline_at=event.at + timedelta(days=14))


def call(company, token, days_ago):
    return ContactEvent.objects.create(client=company, phone_token=token, phone_token_kid='k1', source_system='vicidial', source_record_id=f'c{next(n)}',
                                       source_grade='B', channel='call', direction='outbound', occurred_at=NOW - timedelta(days=days_ago),
                                       masked_label='(916) •••-0001')


def review(company, token, result='none', attorney_days=None):
    return ConversationReview.objects.create(client=company, phone_token=token, channel='text', source_system='twilio', thread_end_at=NOW - timedelta(days=25, minutes=next(n)),
                                             result=result, trusted=True,
                                             attorney_at=NOW - timedelta(days=attorney_days) if attorney_days else None)


@pytest.fixture
def tools(company):
    return (Connection.objects.create(client=company, provider='vicidial', status=Status.CONNECTED),
            Connection.objects.create(client=company, provider='hubspot', status=Status.CONNECTED))


def test_revocation_page_from_real_opt_outs(company, member_user, signed_in, tools):
    dialer, crm = tools
    fine = optout(company, 30, 'a')
    check(company, fine, dialer, 2)
    check(company, fine, crm, 0.5)
    late = optout(company, 30, 'b', method='ai', channel='call', keyword='')
    check(company, late, dialer, None, marked=False, missed=True, urgent=True)
    call(company, 'b', 2)
    page = signed_in(member_user).get('/api/revocation').json()
    assert (page['tests'], page['p90'], page['notSuppressedByDeadline'], page['contactedAfterDeadline']) == (2, 'NEVER', 1, 1)
    assert [s['name'] for s in page['systems']] == ['Vicidial', 'HubSpot'] and page['systems'][1]['contacting'] is False
    rows = {r['channel']: r['cells'] for r in page['rows']}
    assert rows['SMS reply — “STOP”'][0] == {'hours': 2.0, 'tested': True, 'tests': 1}
    assert rows['Spoken on a call'] == [{'hours': None, 'tested': True, 'tests': 1}, {'hours': None, 'tested': False, 'tests': 0}]
    assert {d['label']: d['count'] for d in page['distribution']}['Never'] == 1


def test_revocation_page_before_any_check_says_not_measured(company, member_user, signed_in):
    page = signed_in(member_user).get('/api/revocation').json()
    assert page['medianHours'] is None and page['p90'] is None and 'rows' not in page and 'systems' not in page


def test_opt_outs_table_shows_each_tool(company, member_user, signed_in, tools):
    dialer, crm = tools
    event = optout(company, 1, 'c', method='ai', keyword='')
    OptOutEvent.objects.filter(pk=event.pk).update(counts=False)
    check(company, event, dialer, None, marked=False, urgent=True)
    check(company, event, crm, None, marked=None)
    row = signed_in(member_user).get('/api/optouts').json()[0]
    assert (row['dialerMarked'], row['urgent'], row['counted'], row['words']) == (False, True, False, None)
    assert {t['name']: t['marked'] for t in row['tools']} == {'Vicidial': False, 'HubSpot': None}


def test_overview_ai_card(company, member_user, signed_in, tools):
    assert signed_in(member_user).get('/api/data-health').json()['conversationReview'] is None
    review(company, 'd', 'opted_out')
    event = optout(company, 20, 'd', method='ai', keyword='')
    check(company, event, tools[0], None, marked=False, missed=True, urgent=True)
    card = signed_in(member_user).get('/api/data-health').json()['conversationReview']
    assert card == {'reviewed': 1, 'optOutsFound': 1, 'missed': 1, 'notMarkedFirstCheck': 1}


def test_m08_m09_in_metrics(company, member_user, signed_in, tools):
    check(company, optout(company, 1, 'e'), tools[0], 3)
    codes = {m['code']: m for m in signed_in(member_user).get('/api/metrics').json()}
    assert codes['M08']['display'] == '3.0 h' and 'source' in codes['M08'] and codes['M09']['display'] == 'Not measured'


def test_who_contact_m41_m42_m48_m45(company, tools):
    dialer = tools[0]
    for token, missed in (('f', True), ('g', False), ('h', False)):
        event = optout(company, 25, token, method='ai', keyword='')
        check(company, event, dialer, None if missed else 24, marked=not missed, missed=missed)
    call(company, 'f', 3)
    optout(company, 20, 'w', method='ai', keyword='wrong number')
    call(company, 'w', 2)
    review(company, 'law', attorney_days=10)
    call(company, 'law', 1)
    areas = {a['id']: {c['metric']: c for c in a['checks']} for a in who_contact(company)['areas']}
    assert areas['idn']['M41']['result'] == '1 of 3' and areas['idn']['M41']['state'] == 'fail'
    assert areas['idn']['M42']['result'] == '67%'
    assert areas['rnd']['M48']['result'] == '1 contact'
    assert areas['lit']['M45']['result'] == '1 of 1'


def test_who_contact_leaves_ai_checks_to_the_sample_before_any_ai(company):
    areas = {a['id']: a for a in who_contact(company)['areas']}
    assert 'lit' not in areas and all(c['metric'] not in ('M41', 'M42', 'M48') for a in areas.values() for c in a['checks'])
