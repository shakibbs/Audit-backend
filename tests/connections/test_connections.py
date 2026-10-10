"""Connections live on the client company page: added, edited, tested and removed there."""
from unittest import mock

import pytest
from django.core import mail
from django.db import connection as db

from apps.access_log.models import AccessEntry
from apps.clients.models import Client
from apps.connections.models import Connection, Status
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

SECRET = 'tw-auth-token-very-secret-123'
TWILIO_OK = mock.patch('apps.connections.testers._get', return_value={'friendly_name': 'SunPath'})


@pytest.fixture
def staff_client(client):
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    return client


def company_fields(company=None, **over):
    return {'name': company.name if company else 'New Solar Co', 'industry': 'Solar', 'plan': 'growth',
            'start_date': '2026-10-01', 'status': 'onboarding', 'counsel_directed': 'on', **over}


def management(prefix, total, initial=0):
    return {f'{prefix}-TOTAL_FORMS': total, f'{prefix}-INITIAL_FORMS': initial,
            f'{prefix}-MIN_NUM_FORMS': 0, f'{prefix}-MAX_NUM_FORMS': 1000}


def connection_row(i, connection=None, **fields):
    row = {'provider': 'twilio', 'label': '', 'account': '', 'key': '', 'secret': '', **fields}
    data = {f'connections-{i}-{k}': v for k, v in row.items()}
    if connection is not None:
        data[f'connections-{i}-id'] = connection.pk
        data[f'connections-{i}-client'] = connection.client_id
    return data


def save_page(staff_client, company, rows, initial=0):
    """Posts the client page the way the browser does: company fields + every tab's form data."""
    data = {**company_fields(company), **management('connections', len(rows), initial),
            **management('users', 0), **management('invites', 0), **management('contract', 0), **management('documents', 0)}
    for row in rows:
        data.update(row)
    url = f'/civ-admin/clients/client/{company.pk}/change/' if company else '/civ-admin/clients/client/add/'
    return staff_client.post(url, data)


@pytest.mark.django_db
def test_new_client_and_its_connection_are_saved_together(staff_client):
    with TWILIO_OK:
        response = save_page(staff_client, None, [connection_row(0, account='AC123', key=SECRET)])
    assert response.status_code == 302, response.content.decode()[:2000]
    company = Client.objects.get(name='New Solar Co')
    saved = company.connections.get()
    assert saved.status == Status.CONNECTED and saved.get_credentials() == {'account': 'AC123', 'key': SECRET}
    company.refresh_from_db()
    assert company.access_level == 1
    assert AccessEntry.objects.filter(action='connection_added', client_id=company.pk).exists()


@pytest.mark.django_db
def test_key_is_locked_and_never_shown_on_the_page(staff_client, company):
    with TWILIO_OK:
        save_page(staff_client, company, [connection_row(0, account='AC123', key=SECRET)])
    with db.cursor() as cursor:
        cursor.execute('SELECT credentials FROM connection')
        assert SECRET not in cursor.fetchone()[0]
    page = staff_client.get(f'/civ-admin/clients/client/{company.pk}/change/').content.decode()
    assert SECRET not in page and 'Saved · hidden' in page and 'Connections' in page


@pytest.mark.django_db
def test_editing_with_empty_key_keeps_the_saved_one(staff_client, company):
    with TWILIO_OK:
        save_page(staff_client, company, [connection_row(0, account='AC123', key=SECRET)])
        saved = Connection.objects.get()
        save_page(staff_client, company, [connection_row(0, saved, label='Main')], initial=1)
    saved.refresh_from_db()
    assert saved.label == 'Main' and saved.get_credentials()['key'] == SECRET


@pytest.mark.django_db
def test_tool_without_a_tester_is_saved_not_tested(staff_client, company):
    save_page(staff_client, company, [connection_row(0, provider='convoso', key='abc')])
    assert Connection.objects.get().status == Status.UNTESTED
    company.refresh_from_db()
    assert company.access_level == 0


@pytest.mark.django_db
def test_removing_a_connection_on_the_page(staff_client, company):
    save_page(staff_client, company, [connection_row(0, provider='convoso', key='abc')])
    saved = Connection.objects.get()
    save_page(staff_client, company, [{**connection_row(0, saved, provider='convoso'), 'connections-0-DELETE': 'on'}], initial=1)
    assert not Connection.objects.exists()
    assert AccessEntry.objects.filter(action='connection_removed').exists()


@pytest.mark.django_db
def test_oauth_tool_refuses_a_key_then_sends_a_connect_link(staff_client, company, admin_user):
    page = save_page(staff_client, company, [connection_row(0, provider='salesforce', key='should-not-be-here')])
    assert page.status_code == 200 and not Connection.objects.exists()
    save_page(staff_client, company, [connection_row(0, provider='salesforce')])
    saved = Connection.objects.get()
    assert saved.status == Status.WAITING
    staff_client.post(f'/civ-admin/clients/client/{company.pk}/connections/{saved.pk}/send-link/')
    assert mail.outbox[0].to == [admin_user.email]


@pytest.mark.django_db
def test_test_button_on_a_row(staff_client, company):
    saved = Connection(client=company, provider='twilio')
    saved.set_credentials({'account': 'AC1', 'key': SECRET})
    saved.save()
    with TWILIO_OK:
        response = staff_client.post(f'/civ-admin/clients/client/{company.pk}/connections/{saved.pk}/test/')
    assert response.status_code == 302
    saved.refresh_from_db()
    assert saved.status == Status.CONNECTED


@pytest.mark.django_db
def test_client_page_shows_tabs_summary_and_activity(staff_client, company, admin_user):
    page = staff_client.get(f'/civ-admin/clients/client/{company.pk}/change/').content.decode()
    for text in ('General', 'Connections', 'Users', 'Invites', 'Activity', 'Data access', admin_user.email):
        assert text in page


@pytest.mark.django_db
def test_access_level_ladder(company):
    def connect(provider):
        Connection(client=company, provider=provider, status=Status.CONNECTED).save()
    connect('salesforce')  # CRM alone, without contact logs, is still level 0
    company.refresh_from_db(); assert company.access_level == 0
    connect('twilio'); company.refresh_from_db(); assert company.access_level == 1
    connect('trustedform'); company.refresh_from_db(); assert company.access_level == 2
    connect('lead_feed'); company.refresh_from_db(); assert company.access_level == 4
