"""Module 9 step 3: after an opt-out, CiV checks each tool marked the number "do not contact" (pretend tools here).
Not marked after 10 minutes → urgent (portal, no email); still not marked at the deadline → missed (M38); a tool that
can't tell → "not checked", never a fail."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.connections.models import Connection, Status
from apps.contacts.epochs import epoch_for
from apps.contacts.models import ContactEvent
from apps.contacts.normalize import codes_for
from apps.imports.models import CrmCreation
from apps.optouts import marks
from apps.optouts.models import MarkCheck, OptOutEvent
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.sync.connectors import vicidial

pytestmark = pytest.mark.django_db
NOW = timezone.now()
PHONE = '+19165550142'
DNC = set()  # pretend Vicidial do-not-call list


def fake_query(self, sql, params):
    if 'FROM vicidial_log' in sql:
        return [{'phone_code': '1', 'phone_number': PHONE[2:]}]
    if 'vicidial_dnc' in sql:
        return [{'phone_number': p} for p in params if p in DNC][:1]
    return []


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    DNC.clear()
    monkeypatch.setattr(vicidial.Vicidial, '__init__', lambda self, connection: None)
    monkeypatch.setattr(vicidial.Vicidial, 'query', fake_query)


def optout(company, minutes_ago=11, method='ai', system='ai_conversation', at=None):
    token = codes_for(company).token(PHONE)
    when = at or NOW - timedelta(minutes=minutes_ago)
    ContactEvent.objects.create(client=company, phone_token=token, phone_token_kid='k1', source_system='vicidial', source_record_id='outbound:77',
                                source_grade='B', channel='call', direction='outbound', occurred_at=when - timedelta(minutes=1),
                                epoch=epoch_for(company.pk, token, when))
    event = OptOutEvent.objects.create(client=company, phone_token=token, at=when, channel='call', method=method,
                                       source_system=system, source_record_id=f'r-{when.timestamp()}')
    OptOutEvent.objects.filter(pk=event.pk).update(created_at=when)
    return event


def dialer(company):
    return Connection.objects.create(client=company, provider='vicidial', status=Status.CONNECTED)


def test_marked_in_the_dialer_is_fine(company):
    dialer(company)
    DNC.add(PHONE[2:])
    optout(company)
    marks.run(company, NOW)
    row = MarkCheck.objects.get()
    assert row.marked is True and row.urgent_at is None and row.marked_at == NOW


def test_not_marked_after_ten_minutes_is_urgent(company):
    dialer(company)
    optout(company)
    marks.run(company, NOW)
    row = MarkCheck.objects.get()
    assert row.marked is False and row.urgent_at == NOW


def test_too_early_waits(company):
    dialer(company)
    optout(company, minutes_ago=3)
    assert marks.run(company, NOW) == 0


def test_still_not_marked_at_the_deadline_is_missed_m38(company):
    dialer(company)
    event = optout(company, at=NOW - timedelta(days=20))
    marks.run(company, NOW - timedelta(days=20) + timedelta(minutes=11))
    marks.run(company, NOW)
    row = MarkCheck.objects.get()
    assert row.missed and row.urgent_at is not None
    m38 = marks.missed_optouts(company, event.at - timedelta(days=1), NOW)
    assert (m38['code'], m38['value']) == ('M38', 1)


def test_marked_later_is_not_missed(company):
    dialer(company)
    event = optout(company, at=NOW - timedelta(days=20))
    marks.run(company, event.at + timedelta(minutes=11))
    DNC.add(PHONE[2:])
    marks.run(company, event.at + timedelta(hours=2))
    marks.run(company, NOW)
    row = MarkCheck.objects.get()
    assert row.marked and not row.missed and row.urgent_at is not None  # the alert stays in the history


def test_marked_then_unmarked_a_day_later_is_urgent(company):
    dialer(company)
    DNC.add(PHONE[2:])
    event = optout(company, at=NOW - timedelta(days=2))
    marks.run(company, event.at + timedelta(minutes=11))
    DNC.clear()
    marks.run(company, event.at + timedelta(days=1, hours=1))
    row = MarkCheck.objects.get()
    assert row.day_check_done and row.marked is False and row.urgent_at == event.at + timedelta(days=1, hours=1)


def test_a_tool_that_cant_tell_is_not_checked_not_a_fail(company):
    Connection.objects.create(client=company, provider='five9', status=Status.CONNECTED)
    Connection.objects.create(client=company, provider='twilio', status=Status.CONNECTED)
    optout(company)
    marks.run(company, NOW)
    assert set(MarkCheck.objects.values_list('marked', flat=True)) == {None}
    assert not MarkCheck.objects.filter(urgent_at__isnull=False).exists()
    assert marks.missed_optouts(company, NOW - timedelta(days=1), NOW)['value'] is None


def test_twilio_blocks_stop_words_itself(company):
    Connection.objects.create(client=company, provider='twilio', status=Status.CONNECTED)
    optout(company, method='keyword', system='twilio')
    marks.run(company, NOW)
    assert MarkCheck.objects.get().marked is True


def test_crm_uses_the_synced_do_not_call_field(company):
    Connection.objects.create(client=company, provider='hubspot', status=Status.CONNECTED)
    token = codes_for(company).token(PHONE)
    record = CrmCreation.objects.create(client=company, source_system='hubspot', record_id='h1', created_at=NOW, opted_out=False, phone_tokens=[token])
    optout(company)
    marks.run(company, NOW)
    assert MarkCheck.objects.get().marked is False
    record.opted_out = True
    record.save()
    marks.run(company, NOW + timedelta(hours=2))
    assert MarkCheck.objects.get().marked is True


def test_lifted_opt_outs_are_not_checked(company):
    dialer(company)
    event = optout(company)
    OptOutEvent.objects.filter(pk=event.pk).update(lifted_at=NOW)
    assert marks.run(company, NOW) == 0
