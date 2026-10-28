"""People are added and edited on their company's page (Users tab); there is no separate list in the menu."""
import pytest
from django.core import mail

from apps.access_log.models import AccessEntry
from apps.accounts.models import ClientUser, Invite
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD


@pytest.fixture
def staff_client(client):
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    return client


def page_data(company, users_rows=(), users_initial=0):
    data = {'name': company.name, 'industry': 'Solar', 'plan': 'growth', 'start_date': '2026-10-01',
            'status': 'active'}
    for prefix, total, initial in (('connections', 0, 0), ('users', len(users_rows), users_initial), ('invites', 0, 0), ('invites-2', 0, 0), ('contract', 0, 0), ('documents', 0, 0)):
        data.update({f'{prefix}-TOTAL_FORMS': total, f'{prefix}-INITIAL_FORMS': initial,
                     f'{prefix}-MIN_NUM_FORMS': 0, f'{prefix}-MAX_NUM_FORMS': 1000})
    for i, row in enumerate(users_rows):
        data.update({f'users-{i}-{k}': v for k, v in row.items()})
    return data


@pytest.mark.django_db
def test_inviting_someone_sends_an_invitation_with_the_lawyer_tick(staff_client, company):
    """Owner decision 2026-10-22: people are invited (7-day link, own password), with a "lawyer" tick box."""
    data = page_data(company)
    data.update({'invites-2-TOTAL_FORMS': 1, 'invites-2-0-name': 'Nia New', 'invites-2-0-email': 'Nia@SunPath.com',
                 'invites-2-0-role': 'member', 'invites-2-0-is_counsel': 'on'})
    response = staff_client.post(f'/civ-admin/clients/client/{company.pk}/change/', data)
    assert response.status_code == 302, response.content.decode()[:1500]
    invite = Invite.objects.get(email='nia@sunpath.com')
    assert invite.client == company and invite.is_counsel and invite.role == 'member'
    assert not ClientUser.objects.filter(email='nia@sunpath.com').exists()  # an account only once they choose a password
    assert mail.outbox[0].to == ['nia@sunpath.com'] and 'invite=' in mail.outbox[0].body and 'lawyer' in mail.outbox[0].body
    assert AccessEntry.objects.filter(action='invite_sent', client_id=company.pk).exists()


@pytest.mark.django_db
def test_resend_gives_a_new_link_and_the_old_one_stops(staff_client, company):
    data = page_data(company)
    data.update({'invites-2-TOTAL_FORMS': 1, 'invites-2-0-name': 'Nia', 'invites-2-0-email': 'nia@sunpath.com', 'invites-2-0-role': 'member'})
    staff_client.post(f'/civ-admin/clients/client/{company.pk}/change/', data)
    invite = Invite.objects.get()
    old = invite.token_hash
    response = staff_client.post(f'/civ-admin/clients/client/{company.pk}/invites/{invite.pk}/resend/')
    assert response.status_code == 302 and response['Location'].endswith('#invites')
    invite.refresh_from_db()
    assert invite.token_hash != old and len(mail.outbox) == 2


@pytest.mark.django_db
def test_a_new_client_needs_its_admin_and_gets_an_invitation(staff_client):
    base = {'name': 'Bright Solar', 'industry': 'Solar', 'plan': 'growth', 'start_date': '2026-10-01', 'status': 'onboarding'}
    for prefix in ('connections', 'contract', 'documents'):
        base.update({f'{prefix}-TOTAL_FORMS': 0, f'{prefix}-INITIAL_FORMS': 0, f'{prefix}-MIN_NUM_FORMS': 0, f'{prefix}-MAX_NUM_FORMS': 1000})
    page = staff_client.post('/civ-admin/clients/client/add/', base)
    assert page.status_code == 200 and "Enter the client Admin" in page.content.decode()  # not saved without its Admin
    response = staff_client.post('/civ-admin/clients/client/add/', {**base, 'admin_name': 'Dana Ruiz', 'admin_email': 'Dana@Bright.com'})
    assert response.status_code == 302, response.content.decode()[:1500]
    invite = Invite.objects.get(email='dana@bright.com')
    assert invite.role == 'admin' and invite.client.name == 'Bright Solar'
    assert mail.outbox[0].to == ['dana@bright.com'] and 'as an Admin' in mail.outbox[0].body
    assert mail.outbox[0].alternatives[0].mimetype == 'text/html'  # the designed email, with a plain-text copy


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


@pytest.mark.django_db
def test_admin_panel_invites_are_accepted_like_a_real_browser(staff_client):
    """End to end, with no all-companies view: a new client's Admin and a lawyer invited from the admin panel each open
    their link, choose a password and are signed in with the right role; the link then stops working."""
    import re

    from django.test import Client as Browser

    from apps.tenancy.scope import _scope
    base = {'name': 'Bright Solar', 'industry': 'Solar', 'plan': 'growth', 'start_date': '2026-10-01', 'status': 'onboarding',
            'admin_name': 'Dana Ruiz', 'admin_email': 'dana@bright.com'}
    for prefix in ('connections', 'contract', 'documents'):
        base.update({f'{prefix}-TOTAL_FORMS': 0, f'{prefix}-INITIAL_FORMS': 0, f'{prefix}-MIN_NUM_FORMS': 0, f'{prefix}-MAX_NUM_FORMS': 1000})
    assert staff_client.post('/civ-admin/clients/client/add/', base).status_code == 302
    from apps.clients.models import Client
    company = Client.objects.get(name='Bright Solar')
    data = page_data(company)
    data.update({'invites-2-TOTAL_FORMS': 1, 'invites-2-0-name': 'Alex Kim', 'invites-2-0-email': 'alex@kimlaw.com',
                 'invites-2-0-role': 'member', 'invites-2-0-is_counsel': 'on'})
    staff_client.post(f'/civ-admin/clients/client/{company.pk}/change/', data)
    links = {m.to[0]: re.search(r'invite=([\w-]+)', m.body).group(1) for m in mail.outbox}
    with _scope('', ''):
        for email, role, lawyer in (('dana@bright.com', 'admin', False), ('alex@kimlaw.com', 'member', True)):
            b = Browser()
            assert b.get(f'/api/invites/check?token={links[email]}').json()['clientName'] == 'Bright Solar'
            session = b.post('/api/invites/accept', {'token': links[email], 'password': PASSWORD}, content_type='application/json').json()
            assert (session['role'], session['isCounsel'], session['clientName']) == (role, lawyer, 'Bright Solar'), session
            assert b.get('/api/users').status_code == 200  # signed in to their own company
            again = Browser().post('/api/invites/accept', {'token': links[email], 'password': PASSWORD}, content_type='application/json')
            assert again.status_code == 400  # one use


@pytest.mark.django_db
def test_the_only_admin_cannot_be_turned_off_or_made_a_member(staff_client, company, admin_user, member_user):
    """QA 2026-10-23: a company keeps at least one active Admin (the portal already refused this)."""
    def row(user, **change):
        base = {'id': user.pk, 'client': company.pk, 'name': user.name, 'email': user.email, 'role': user.role,
                'is_active': 'on' if user.is_active else ''}
        base.update(change)
        return {k: v for k, v in base.items() if v != ''}
    off = page_data(company, [row(admin_user, is_active=''), row(member_user)], users_initial=2)
    reply = staff_client.post(f'/civ-admin/clients/client/{company.pk}/change/', off)
    assert reply.status_code == 200 and 'A company needs at least one active Admin' in reply.content.decode()
    admin_user.refresh_from_db()
    assert admin_user.is_active and admin_user.role == 'admin'
    demoted = page_data(company, [row(admin_user, role='member'), row(member_user)], users_initial=2)
    assert staff_client.post(f'/civ-admin/clients/client/{company.pk}/change/', demoted).status_code == 200
    # make the member Admin first, then the old Admin can go, in the same save
    swap = page_data(company, [row(admin_user, is_active=''), row(member_user, role='admin')], users_initial=2)
    assert staff_client.post(f'/civ-admin/clients/client/{company.pk}/change/', swap).status_code == 302
    admin_user.refresh_from_db()
    member_user.refresh_from_db()
    assert not admin_user.is_active and member_user.role == 'admin'


@pytest.mark.django_db
def test_no_password_link_for_someone_turned_off(staff_client, company, member_user):
    """QA 2026-10-23: the button opened a "not found" page for a turned-off person."""
    member_user.is_active = False
    member_user.save()
    page = staff_client.get(f'/civ-admin/clients/client/{company.pk}/change/').content.decode()
    assert 'Turned off: tick' in page
    reply = staff_client.post(f'/civ-admin/clients/client/{company.pk}/users/{member_user.pk}/password-link/', follow=True)
    assert reply.status_code == 200 and 'is turned off' in reply.content.decode() and not mail.outbox
