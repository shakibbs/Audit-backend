"""Who You Contact → "Each list at a glance" (owner 2026-11-16): one plain answer per list, from database counts."""
from datetime import timedelta

import pytest

from apps.metrics.who import who_contact
from apps.uploads.models import DncCheck, InternalListEntry, RndQuery, Source
from tests.metrics.test_who import TODAY, call, upload

pytestmark = pytest.mark.django_db


def lists(company):
    return {x['col']: x for x in who_contact(company)['glance']['lists']}


def test_nothing_uploaded_is_cant_tell_with_an_upload_button(company):
    call(company)
    got = lists(company)
    assert [got[c]['verdict'] for c in ('national', 'state', 'internal', 'reassigned')] == ["Can't tell"] * 4
    assert all(got[c]['upload'] and got[c]['tone'] == 'gray' for c in got)
    assert who_contact(company)['glance']['contacts'] == 1


def test_national_counts_checks_in_the_31_days_before(company):
    for token in ('p1', 'p2', 'p3', 'p4'):
        call(company, token, days_ago=2)
    up = upload(company, Source.DNC_CHECKS)
    DncCheck.objects.create(client=company, upload=up, phone_token='p1', checked_on=TODAY - timedelta(days=10), listed=False, list_name='national')
    DncCheck.objects.create(client=company, upload=up, phone_token='p2', checked_on=TODAY - timedelta(days=3), listed=False, list_name='')  # no name = national
    DncCheck.objects.create(client=company, upload=up, phone_token='p3', checked_on=TODAY - timedelta(days=60), listed=False, list_name='national')  # too old
    DncCheck.objects.create(client=company, upload=up, phone_token='p4', checked_on=TODAY, listed=False, list_name='national')  # after the call
    got = lists(company)
    assert got['national']['verdict'] == 'Partly checked' and got['national']['count'] == {'n': 2, 'label': 'not checked'}
    assert got['national']['text'].startswith('2 of 4 contacts (50%)')
    # national rows only: State DNC is "Not checked" (the file shows it was not done), not "Can't tell"
    assert got['state']['verdict'] == 'Not checked' and got['state']['tone'] == 'bad' and got['state']['upload']


def test_state_rows_count_for_state(company):
    call(company, 'p1')
    up = upload(company, Source.DNC_CHECKS)
    DncCheck.objects.create(client=company, upload=up, phone_token='p1', checked_on=TODAY - timedelta(days=5), listed=False, list_name='CA')
    got = lists(company)
    assert got['state']['verdict'] == 'Checked' and got['state']['count'] is None
    assert got['national']['verdict'] == 'Not checked'


def test_internal_list_counts_numbers_called_anyway(company):
    call(company, 'p1', days_ago=2)
    call(company, 'p1', days_ago=1)  # same number twice: one number
    call(company, 'p2', days_ago=2)  # joined the list after the call: fine
    up = upload(company, Source.INTERNAL_LIST)
    InternalListEntry.objects.create(client=company, upload=up, phone_token='p1', added_on=TODAY - timedelta(days=9))
    InternalListEntry.objects.create(client=company, upload=up, phone_token='p2', added_on=TODAY)
    got = lists(company)['internal']
    assert got['verdict'] == 'Checked, 1 called anyway' and got['tone'] == 'bad' and got['count'] == {'n': 1, 'label': 'called anyway'}
    assert '2 numbers' in got['text']


def test_reassigned_needs_a_not_reassigned_answer(company):
    call(company, 'p1')
    call(company, 'p2')
    up = upload(company, Source.RND_QUERIES)
    RndQuery.objects.create(client=company, upload=up, phone_token='p1', queried_on=TODAY - timedelta(days=4), result='no')
    RndQuery.objects.create(client=company, upload=up, phone_token='p2', queried_on=TODAY - timedelta(days=4), result='yes')
    got = lists(company)['reassigned']
    assert got['verdict'] == 'Partly checked' and got['count'] == {'n': 1, 'label': 'not checked'}


def test_no_contacts_says_so(company):
    upload(company, Source.DNC_CHECKS)
    DncCheck.objects.create(client=company, upload=upload(company, Source.DNC_CHECKS), phone_token='p1', checked_on=TODAY, listed=False, list_name='national')
    assert lists(company)['national']['verdict'] == 'No contacts'
