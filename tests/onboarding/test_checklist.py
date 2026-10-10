import pytest

from apps.access_log.models import AccessEntry
from apps.connections.models import Connection, Status
from apps.onboarding.progress import checklist
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD


@pytest.fixture
def staff_client(client):
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    return client


def done(company):
    return {s['code'] for s in checklist(company)['steps'] if s['done']}


@pytest.mark.django_db
def test_new_client_starts_with_nothing_done(company):
    progress = checklist(company)
    assert progress['done'] == 0 and progress['total'] == 7 and not progress['complete']


@pytest.mark.django_db
def test_automatic_steps_tick_themselves(company, admin_user):
    Connection(client=company, provider='twilio', status=Status.CONNECTED).save()
    Connection(client=company, provider='convoso', status=Status.UNTESTED).save()  # saved but not connected: not done
    assert done(company) == {'texting', 'client_admin'}


@pytest.mark.django_db
def test_staff_ticks_and_unticks_a_manual_step(staff_client, company):
    url = f'/civ-admin/clients/client/{company.pk}/onboarding/agreement/'
    assert staff_client.post(url).status_code == 302
    assert 'agreement' in done(company)
    assert checklist(company)['steps'][0]['done_by'] == 'Team'
    staff_client.post(url)
    assert 'agreement' not in done(company)
    assert list(AccessEntry.objects.filter(client_id=company.pk).values_list('action', flat=True).order_by('at')) == \
        ['onboarding_step_done', 'onboarding_step_undone']


@pytest.mark.django_db
def test_automatic_steps_cannot_be_ticked_by_hand(staff_client, company):
    assert staff_client.post(f'/civ-admin/clients/client/{company.pk}/onboarding/dialer/').status_code == 403
    assert staff_client.get(f'/civ-admin/clients/client/{company.pk}/onboarding/agreement/').status_code == 405


@pytest.mark.django_db
def test_card_on_client_page_and_column_in_list(staff_client, company):
    page = staff_client.get(f'/civ-admin/clients/client/{company.pk}/change/').content.decode()
    assert 'Onboarding' in page and 'Annex C signed' in page and 'Mark done' in page
    assert '0 of 7' in staff_client.get('/civ-admin/clients/client/').content.decode()
