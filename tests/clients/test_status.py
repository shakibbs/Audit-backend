"""Client stages: Trial → Onboarding → Active → Paused → Ended, with history; Ended blocks sign-in."""
import pytest

from apps.access_log.models import AccessEntry
from apps.clients.models import Client, StatusChange
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD


@pytest.fixture
def staff_client(client):
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    return client


def save(staff_client, company, status, reason=''):
    data = {'name': company.name, 'industry': 'Solar', 'plan': 'growth', 'start_date': '2026-10-01',
            'status': status, 'status_reason': reason, 'counsel_directed': 'on'}
    for prefix in ('connections', 'users', 'invites', 'contract', 'documents'):
        data.update({f'{prefix}-TOTAL_FORMS': 0, f'{prefix}-INITIAL_FORMS': 0, f'{prefix}-MIN_NUM_FORMS': 0, f'{prefix}-MAX_NUM_FORMS': 1000})
    response = staff_client.post(f'/civ-admin/clients/client/{company.pk}/change/', data)
    assert response.status_code == 302, response.content.decode()[:1500]
    company.refresh_from_db()


@pytest.mark.django_db
def test_new_clients_start_in_onboarding(company):
    assert company.status == Client.Status.ONBOARDING and company.is_active


@pytest.mark.django_db
def test_changing_stage_keeps_history_with_reason(staff_client, company):
    save(staff_client, company, 'active', 'Contract signed')
    change = StatusChange.objects.get()
    assert (change.old_status, change.new_status, change.reason, change.changed_by.name) == ('onboarding', 'active', 'Contract signed', 'Team')
    assert company.status_changed_at is not None
    assert AccessEntry.objects.filter(action='client_status_changed', object='Onboarding → Active (Contract signed)').exists()


@pytest.mark.django_db
def test_saving_without_a_stage_change_adds_no_history(staff_client, company):
    save(staff_client, company, 'onboarding')
    assert not StatusChange.objects.exists()


@pytest.mark.django_db
def test_ended_blocks_sign_in_and_reopening_allows_it(staff_client, company, admin_user, api):
    save(staff_client, company, 'ended', 'Contract over')
    assert company.is_active is False and not company.can_sync
    sign_in = {'email': admin_user.email, 'password': PASSWORD}
    assert api.call('post', '/api/session/sign-in', sign_in).status_code == 400
    save(staff_client, company, 'active')
    assert company.is_active is True
    assert api.call('post', '/api/session/sign-in', sign_in).status_code == 200


@pytest.mark.django_db
def test_paused_keeps_sign_in_but_stops_sync(staff_client, company):
    save(staff_client, company, 'paused')
    assert company.is_active and not company.can_sync


@pytest.mark.django_db
def test_stage_shows_in_list_and_page(staff_client, company):
    save(staff_client, company, 'active', 'Go live')
    assert 'Active' in staff_client.get('/civ-admin/clients/client/').content.decode()
    page = staff_client.get(f'/civ-admin/clients/client/{company.pk}/change/').content.decode()
    assert 'Stage history' in page and 'Go live' in page
