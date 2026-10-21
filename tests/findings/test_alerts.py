"""Module 11 step 3: alerts gathered from what CiV already knows; updated, not repeated; lasting ones resolve;
reviewed by anyone who can see them; lawyer-only mode; kept forever."""
from datetime import UTC, date, datetime, timedelta

import pytest
from django.utils import timezone

from apps.alerts.models import Alert
from apps.alerts.raise_ import refresh
from apps.connections.models import Connection, Status
from apps.consent.models import ConsentResult
from apps.contacts.models import ContactEvent
from apps.optouts.models import MarkCheck, OptOutEvent
from apps.reconcile.models import PeriodIntegrity

pytestmark = pytest.mark.django_db
n = iter(range(10**6))


def after_stop(company, when):
    c = ContactEvent.objects.create(client=company, phone_token=f'p{next(n)}', phone_token_kid='k1', source_system='twilio',
                                    source_record_id=f'm{next(n)}', source_grade='C', channel='text', direction='outbound', occurred_at=when)
    ConsentResult.objects.create(client=company, contact=c, variant='strict', status='no_proof', codes=['NP_AFTER_OPT_OUT'],
                                 evaluation_as_of=when, rulebook_version='3.0')


def keys(company):
    return {a.key: a for a in Alert.objects.filter(client=company)}


def test_contacts_after_an_opt_out_raise_one_alert_per_day_updated_not_repeated(company):
    now = timezone.now()
    after_stop(company, now - timedelta(hours=2))
    refresh(company, now)
    after_stop(company, now - timedelta(hours=1))
    refresh(company, now)
    alert = Alert.objects.get()
    assert (alert.severity, alert.count) == ('High', 2) and alert.title.startswith('2 contacts after an opt-out')
    after_stop(company, now - timedelta(days=30))  # old: no alert
    refresh(company, now)
    assert Alert.objects.count() == 1


def test_a_stale_tool_resolves_by_itself_and_stays_in_the_history(company):
    tool = Connection.objects.create(client=company, provider='vicidial', status=Status.STALE)
    refresh(company)
    assert keys(company)[f'stale-{tool.pk}'].title == 'Vicidial has stopped sending data'
    tool.status = Status.CONNECTED
    tool.save()
    assert refresh(company) == 0
    assert keys(company)[f'stale-{tool.pk}'].resolved_at is not None


def test_unmarked_stop_and_incomplete_month(company):
    tool = Connection.objects.create(client=company, provider='vicidial', status=Status.CONNECTED)
    stop = OptOutEvent.objects.create(client=company, phone_token='x', at=timezone.now(), channel='call', method='ai',
                                      source_system='ai_conversation', source_record_id='r1')
    MarkCheck.objects.create(client=company, optout=stop, connection=tool, marked=False, checked_at=timezone.now(), urgent_at=timezone.now())
    PeriodIntegrity.objects.create(client=company, period=date(2026, 9, 1), completeness=0.92, incomplete=True)
    refresh(company)
    found = keys(company)
    assert found[f'unmarked-{stop.pk}-{tool.pk}'].severity == 'High'
    assert found['incomplete-2026-09'].detail.startswith('CiV holds about 92%')


def test_review_and_lawyer_only_mode(company, admin_user, member_user, signed_in, api):
    Connection.objects.create(client=company, provider='vicidial', status=Status.STALE)
    refresh(company)
    company.counsel_directed = True
    company.save()
    assert signed_in(member_user).get('/api/alerts').json() == []  # a Member in lawyer-only mode sees none
    assert api.get('/api/actions').json() == []
    company.counsel_directed = False
    company.save()
    row = api.get('/api/alerts').json()[0]
    assert row['routedTo'] == 'all'
    reviewed = api.call('post', f"/api/alerts/{row['id']}/review").json()
    assert reviewed['reviewed'] and reviewed['reviewedBy'] == member_user.name
    assert Alert.objects.get().reviewed
