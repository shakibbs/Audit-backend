from unittest import mock

import pytest
from django.core import mail
from django.db import connection as db

from apps.access_log.models import AccessEntry
from apps.connections.models import Connection, Status
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

SECRET = 'tw-auth-token-very-secret-123'


@pytest.fixture
def staff_client(client):
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    return client


def add(staff_client, company, **fields):
    data = {'client': company.pk, 'provider': 'twilio', 'label': '', 'account': '', 'key': '', 'secret': '',
            'connections-TOTAL_FORMS': 0, 'connections-INITIAL_FORMS': 0, **fields}
    return staff_client.post('/civ-admin/connections/connection/add/', data)


@pytest.mark.django_db
def test_key_is_locked_in_the_database_and_never_shown(staff_client, company):
    with mock.patch('apps.connections.testers._get', return_value={'friendly_name': 'SunPath'}):
        assert add(staff_client, company, account='AC123', key=SECRET).status_code == 302
    saved = Connection.objects.get()
    assert saved.get_credentials() == {'account': 'AC123', 'key': SECRET}
    with db.cursor() as cursor:
        cursor.execute('SELECT credentials FROM connection')
        assert SECRET not in cursor.fetchone()[0]
    page = staff_client.get(f'/civ-admin/connections/connection/{saved.pk}/change/').content.decode()
    assert SECRET not in page and 'Saved · hidden' in page


@pytest.mark.django_db
def test_saving_a_twilio_key_tests_it_and_sets_access_level(staff_client, company):
    with mock.patch('apps.connections.testers._get', return_value={'friendly_name': 'SunPath'}):
        add(staff_client, company, account='AC123', key=SECRET)
    saved = Connection.objects.get()
    assert saved.status == Status.CONNECTED and 'SunPath' in saved.last_message
    company.refresh_from_db()
    assert company.access_level == 1
    assert AccessEntry.objects.filter(action='connection_added').exists()
    assert AccessEntry.objects.filter(action='connection_tested').exists()


@pytest.mark.django_db
def test_tool_without_a_tester_is_saved_not_tested(staff_client, company):
    add(staff_client, company, provider='convoso', key='abc')
    saved = Connection.objects.get()
    assert saved.status == Status.UNTESTED
    company.refresh_from_db()
    assert company.access_level == 0  # only a tested, connected tool counts


@pytest.mark.django_db
def test_empty_key_on_edit_keeps_the_saved_one(staff_client, company):
    with mock.patch('apps.connections.testers._get', return_value={}):
        add(staff_client, company, account='AC123', key=SECRET)
        saved = Connection.objects.get()
        data = {'client': company.pk, 'provider': 'twilio', 'label': 'Main', 'account': '', 'key': '', 'secret': ''}
        staff_client.post(f'/civ-admin/connections/connection/{saved.pk}/change/', data)
    saved.refresh_from_db()
    assert saved.label == 'Main' and saved.get_credentials()['key'] == SECRET


@pytest.mark.django_db
def test_oauth_tool_refuses_a_key_and_sends_a_connect_link(staff_client, company, admin_user):
    page = add(staff_client, company, provider='salesforce', key='should-not-be-here')
    assert page.status_code == 200 and not Connection.objects.exists()
    add(staff_client, company, provider='salesforce')
    saved = Connection.objects.get()
    assert saved.status == Status.WAITING
    staff_client.post('/civ-admin/connections/connection/', {'action': 'send_connect_links', '_selected_action': [saved.pk]})
    assert mail.outbox[0].to == [admin_user.email]


@pytest.mark.django_db
def test_access_level_ladder(company):
    def connect(provider):
        c = Connection(client=company, provider=provider, status=Status.CONNECTED)
        c.save()
    connect('salesforce')  # CRM alone, without contact logs, is still level 0
    company.refresh_from_db(); assert company.access_level == 0
    connect('twilio'); company.refresh_from_db(); assert company.access_level == 1
    connect('trustedform'); company.refresh_from_db(); assert company.access_level == 2
    connect('lead_feed'); company.refresh_from_db(); assert company.access_level == 4
