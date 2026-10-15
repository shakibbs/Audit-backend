"""Phone epochs: each contact belongs to one owner's time with the number; a real move splits the timeline."""
import json
from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection as db

from apps.connections.models import Connection, Status
from apps.contacts.epochs import attach, crm_record_seen, split
from apps.contacts.models import ContactEvent, PhoneEpoch
from apps.sync.connector import Record
from apps.tenancy.scope import _scope

pytestmark = pytest.mark.django_db
JAN, AUG, OCT = (datetime(2026, m, 1, tzinfo=UTC) for m in (1, 8, 10))


def call(client, rid, at, person='num1'):
    c = ContactEvent.objects.create(client=client, phone_token=person, phone_token_kid='k1', source_system='convoso',
                                    source_record_id=rid, source_grade='C', channel='call', direction='outbound', occurred_at=at)
    attach(c)
    return c


def epoch_of(contact):
    return ContactEvent.objects.get(pk=contact.pk).epoch.number


def test_a_new_number_has_one_epoch_for_all_its_contacts(company):
    a, b = call(company, '1', JAN), call(company, '2', OCT)
    assert epoch_of(a) == epoch_of(b) == 1 and PhoneEpoch.objects.count() == 1


def test_split_moves_only_later_contacts(company):
    sarah, mike = call(company, '1', JAN), call(company, '2', OCT)
    split(company.pk, 'num1', AUG, PhoneEpoch.Reason.WRONG_NUMBER, 'ai_review')
    assert (epoch_of(sarah), epoch_of(mike)) == (1, 2)
    first, second = PhoneEpoch.objects.order_by('number')
    assert first.ended_at == AUG and second.started_at == AUG and second.ended_at is None and second.reason == 'wrong_number'
    assert epoch_of(call(company, '3', OCT + timedelta(days=1))) == 2  # new contacts land in the right epoch


def test_splitting_twice_and_out_of_order_keeps_time_order(company):
    calls = [call(company, str(m), datetime(2026, m, 15, tzinfo=UTC)) for m in (1, 4, 9)]
    split(company.pk, 'num1', datetime(2026, 8, 1, tzinfo=UTC), 'rnd', 'client_rnd')
    split(company.pk, 'num1', datetime(2026, 3, 1, tzinfo=UTC), 'wrong_number')  # an earlier change, learned later
    assert [epoch_of(c) for c in calls] == [1, 2, 3]
    starts = list(PhoneEpoch.objects.order_by('number').values_list('started_at', flat=True))
    assert starts == [None, datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 8, 1, tzinfo=UTC)]
    assert split(company.pk, 'num1', datetime(2026, 8, 1, tzinfo=UTC), 'rnd').number == 3  # same date again: no new epoch


def crm(client, record_id, tokens, at):
    c = Connection.objects.get_or_create(client=client, provider='hubspot', defaults={'status': Status.CONNECTED})[0]
    crm_record_seen(client, c, Record(record_id, json.dumps({'id': record_id}).encode(), 'crm_record', at), tokens)


def test_a_number_that_moves_to_another_customer_record_starts_a_new_owner(company):
    before = call(company, '1', JAN)
    crm(company, 'contacts:123', ['num1'], JAN)  # Sarah's record has the number
    crm(company, 'contacts:123', ['other'], AUG - timedelta(days=5))  # Sarah's record changes number
    crm(company, 'contacts:987', ['num1'], AUG)  # a different customer now has it
    after = call(company, '2', OCT)
    assert (epoch_of(before), epoch_of(after)) == (1, 2)
    assert PhoneEpoch.objects.get(number=2).reason == 'crm_moved'


def test_a_duplicate_customer_record_is_not_a_new_owner(company):
    crm(company, 'contacts:123', ['num1'], JAN)
    crm(company, 'contacts:555', ['num1'], AUG)  # 123 still has it: a duplicate or a household, not a move
    crm(company, 'contacts:123', ['num1'], OCT)  # the same record updated: nothing new
    assert PhoneEpoch.objects.filter(phone_token='num1').count() <= 1


def test_no_names_stored_and_locked_per_client(company, other_company):
    crm(company, 'contacts:123', ['num1'], JAN)
    call(company, '1', JAN)
    call(other_company, '1', JAN)
    with db.cursor() as cur:
        cur.execute('SELECT * FROM phone_epoch')
        rows = repr(cur.fetchall())
        cur.execute('SELECT * FROM crm_phone_holder')
        rows += repr(cur.fetchall())
    assert 'Sarah' not in rows and 'Mike' not in rows
    with _scope('client', str(company.pk)):
        assert set(PhoneEpoch.objects.values_list('client_id', flat=True)) == {company.pk}


def test_crm_people_reach_the_epoch_watcher():
    from apps.sync import handoff
    assert crm_record_seen in handoff.RECEIVERS
