"""People are added and edited on their company's page (Users tab); there is no separate list in the menu."""
import pytest
from django.core import mail

from apps.access_log.models import AccessEntry
from apps.accounts.models import ClientUser
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD


@pytest.fixture
def staff_client(client):
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    return client


def page_data(company, users_rows=(), users_initial=0):
    data = {'name': company.name, 'industry': 'Solar', 'plan': 'growth', 'start_date': '2026-10-01',
            'status': 'active', 'counsel_directed': 'on'}
    for prefix, total, initial in (('connections', 0, 0), ('users', len(users_rows), users_initial), ('invites', 0, 0), ('contract', 0, 0), ('documents', 0, 0)):
        data.update({f'{prefix}-TOTAL_FORMS': total, f'{prefix}-INITIAL_FORMS': initial,
                     f'{prefix}-MIN_NUM_FORMS': 0, f'{prefix}-MAX_NUM_FORMS': 1000})
    for i, row in enumerate(users_rows):
        data.update({f'users-{i}-{k}': v for k, v in row.items()})
    return data


@pytest.mark.django_db
def test_adding_a_person_on_the_users_tab_sends_a_password_link(staff_client, company):
    row = {'name': 'Nia New', 'email': 'Nia@SunPath.com', 'role': 'member', 'is_active': 'on'}
    response = staff_client.post(f'/civ-admin/clients/client/{company.pk}/change/', page_data(company, [row]))
    assert response.status_code == 302, response.content.decode()[:1500]
    user = ClientUser.objects.get(email='nia@sunpath.com')
    assert user.client == company and not user.has_usable_password()
    assert mail.outbox[0].to == ['nia@sunpath.com'] and 'reset=' in mail.outbox[0].body
    assert AccessEntry.objects.filter(action='user_added', client_id=company.pk).exists()


@pytest.mark.django_db
def test_editing_a_person_on_the_users_tab(staff_client, company, member_user):
    row = {'id': member_user.pk, 'client': company.pk, 'name': 'Sam Lee', 'email': member_user.email,
           'role': 'admin', 'is_counsel': 'on', 'is_active': 'on'}
    staff_client.post(f'/civ-admin/clients/client/{company.pk}/change/', page_data(company, [row], users_initial=1))
    member_user.refresh_from_db()
    assert member_user.role == 'admin' and member_user.is_counsel
    assert not mail.outbox  # editing someone does not email them


@pytest.mark.django_db
def test_password_link_button(staff_client, company, member_user):
    response = staff_client.post(f'/civ-admin/clients/client/{company.pk}/users/{member_user.pk}/password-link/')
    assert response.status_code == 302 and response['Location'].endswith('#users')
    assert mail.outbox[0].to == [member_user.email]


@pytest.mark.django_db
def test_menu_has_no_separate_users_or_invites_page(staff_client):
    page = staff_client.get('/civ-admin/').content.decode()
    assert 'Client companies' in page
    assert '/civ-admin/accounts/clientuser/' not in page and '/civ-admin/accounts/invite/' not in page


@pytest.mark.django_db
def test_client_search_finds_a_person_by_email(staff_client, company, member_user, other_company):
    page = staff_client.get('/civ-admin/clients/client/', {'q': member_user.email}).content.decode()
    assert company.name in page and other_company.name not in page
