"""The same call recorded by two tools is counted once; real separate calls never merge. 'Time' = when the call happened."""
from datetime import UTC, datetime, timedelta

import pytest

from apps.contacts.dedupe import group
from apps.contacts.models import ContactEvent

pytestmark = pytest.mark.django_db
AT = datetime(2026, 10, 1, 14, 0, tzinfo=UTC)


def contact(client, tool, rid, at, person='sarah', channel='call', direction='outbound'):
    c = ContactEvent.objects.create(client=client, phone_token=person, phone_token_kid='k1', source_system=tool, source_record_id=rid,
                                    source_grade='C', channel=channel, direction=direction, occurred_at=at)
    group(c)
    return c


def counted(client):
    return ContactEvent.objects.filter(client=client, is_primary=True).count()


def test_dialer_and_crm_copy_3_seconds_apart_are_one_call(company):
    crm = contact(company, 'hubspot', 'calls:1', AT + timedelta(seconds=3))
    dialer = contact(company, 'convoso', '9001', AT)
    crm.refresh_from_db()
    dialer.refresh_from_db()
    assert crm.dedupe_group == dialer.dedupe_group is not None
    assert dialer.is_primary and not crm.is_primary  # the dialer made the call: it is the main record
    assert counted(company) == 1


def test_same_tool_twice_is_two_real_calls(company):
    contact(company, 'convoso', '9001', AT)
    contact(company, 'convoso', '9002', AT + timedelta(seconds=60))
    assert counted(company) == 2 and not ContactEvent.objects.exclude(dedupe_group=None).exists()


@pytest.mark.parametrize('change', [
    {'at': AT + timedelta(seconds=125)},  # outside the 2-minute window
    {'person': 'tom'}, {'channel': 'text'}, {'direction': 'inbound'},
])
def test_different_time_person_channel_or_direction_stay_separate(company, change):
    contact(company, 'convoso', '9001', AT)
    contact(company, 'hubspot', 'calls:1', change.pop('at', AT + timedelta(seconds=5)), **change)
    assert counted(company) == 2


def test_a_copy_read_hours_later_still_matches_by_calling_time(company):
    dialer = contact(company, 'convoso', '9001', AT)
    later = contact(company, 'hubspot', 'calls:1', AT + timedelta(seconds=40))  # CiV reads it hours later; the call time is what counts
    assert ContactEvent.objects.get(pk=later.pk).dedupe_group == ContactEvent.objects.get(pk=dialer.pk).dedupe_group
    assert counted(company) == 1


def test_three_tools_one_group(company):
    contact(company, 'convoso', '9001', AT)
    contact(company, 'hubspot', 'calls:1', AT + timedelta(seconds=10))
    contact(company, 'twilio', 'CA1', AT - timedelta(seconds=20))
    assert ContactEvent.objects.values('dedupe_group').distinct().count() == 1 and counted(company) == 1


def test_crm_copy_joins_the_nearest_of_two_dialer_calls(company):
    first = contact(company, 'convoso', '9001', AT)
    second = contact(company, 'convoso', '9002', AT + timedelta(seconds=60))
    crm = contact(company, 'hubspot', 'calls:1', AT + timedelta(seconds=55))
    assert ContactEvent.objects.get(pk=crm.pk).dedupe_group == ContactEvent.objects.get(pk=second.pk).dedupe_group
    assert ContactEvent.objects.get(pk=first.pk).dedupe_group is None
    assert counted(company) == 2


def test_unknown_direction_still_matches(company):
    contact(company, 'convoso', '9001', AT)
    contact(company, 'hubspot', 'calls:1', AT + timedelta(seconds=4), direction='unknown')
    assert counted(company) == 1


def test_a_corrected_time_moves_the_copy_out(company):
    contact(company, 'convoso', '9001', AT)
    crm = contact(company, 'hubspot', 'calls:1', AT + timedelta(seconds=4))
    ContactEvent.objects.filter(pk=crm.pk).update(occurred_at=AT + timedelta(hours=2))
    group(ContactEvent.objects.get(pk=crm.pk))
    assert counted(company) == 2 and not ContactEvent.objects.exclude(dedupe_group=None).exists()


def test_other_clients_never_merge(company, other_company):
    contact(company, 'convoso', '9001', AT)
    contact(other_company, 'hubspot', 'calls:1', AT)
    assert counted(company) == 1 and counted(other_company) == 1 and not ContactEvent.objects.exclude(dedupe_group=None).exists()
