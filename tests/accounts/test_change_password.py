"""Owner decision 2026-10-22: every user can change their own password (current one first), "Forgot password" is gone
from the sign-in page, and CiV staff send password links to client people and staff."""
import re

import pytest
from django.core import mail
from django.test import Client as Browser

from apps.access_log.models import AccessEntry
from apps.buyers.models import BuyerOrg, BuyerUser
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db
NEW = 'Brand-new-password-42'


def change(api, current, new=NEW):
    return api.call('post', '/api/session/password', {'current': current, 'password': new})


def test_a_client_user_changes_their_password_and_other_devices_sign_out(company, member_user, signed_in, api):
    other = Browser()
    other.post('/api/session/sign-in', {'email': member_user.email, 'password': PASSWORD}, content_type='application/json')
    signed_in(member_user)
    assert change(api, 'wrong-password').status_code == 400
    assert change(api, PASSWORD, 'short').status_code == 400  # same rules as everywhere
    assert change(api, PASSWORD).status_code == 200
    assert api.call('get', '/api/session').json()['signedIn']  # this device stays in
    assert other.get('/api/session').json()['signedIn'] is False  # the other one is signed out
    member_user.refresh_from_db()
    assert member_user.check_password(NEW)
    assert AccessEntry.objects.filter(action='password_changed', client_id=company.pk).exists()


def test_wrong_current_passwords_lock_like_sign_in(company, member_user, signed_in, api):
    signed_in(member_user)
    for _ in range(5):
        change(api, 'wrong-password')
    assert change(api, PASSWORD).status_code == 429


def test_an_insurer_changes_their_password():
    org = BuyerOrg.objects.create(name='Falcon Risk', domain='falconrisk.com')
    person = BuyerUser(org=org, email='j@falconrisk.com', name='J. Merchant')
    person.set_password(PASSWORD)
    person.save()
    b = Browser()
    b.post('/api/session/sign-in', {'email': person.email, 'password': PASSWORD}, content_type='application/json')
    assert b.post('/api/session/password', {'current': PASSWORD, 'password': NEW}, content_type='application/json').status_code == 200
    assert b.get('/api/session').json()['view'] == 'underwriter'
    person.refresh_from_db()
    assert person.check_password(NEW)


def test_not_signed_in_cannot_change():
    assert Browser().post('/api/session/password', {'current': 'x', 'password': NEW}, content_type='application/json').status_code in (401, 403)


@pytest.fixture
def staff(client):
    user = StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD)
    client.force_login(user)
    return client


def test_an_insurer_password_link_works_once(staff):
    """Staff send it from the Insurers page (kept for insurers only, owner 2026-10-22)."""
    org = BuyerOrg.objects.create(name='Falcon Risk', domain='falconrisk.com')
    person = BuyerUser.objects.create(org=org, email='j@falconrisk.com', name='J. Merchant')
    response = staff.post(f'/civ-admin/buyers/buyerorg/{org.pk}/people/{person.pk}/password-link/')
    assert response.status_code == 302 and mail.outbox[0].to == ['j@falconrisk.com']
    link = re.search(r'reset=(b-[\w.-]+)', mail.outbox[0].body).group(1)
    b = Browser()
    assert b.post('/api/session/reset/confirm', {'link': link, 'password': NEW}, content_type='application/json').status_code == 200
    person.refresh_from_db()
    assert person.check_password(NEW)
    assert b.post('/api/session/reset/confirm', {'link': link, 'password': 'Another-new-pass-77'}, content_type='application/json').status_code == 400
    assert b.post('/api/session/reset/confirm', {'link': link[2:], 'password': NEW}, content_type='application/json').status_code == 400  # not a client link


def test_staff_change_their_own_password_in_the_panel(staff):
    page = staff.get('/civ-admin/password_change/')
    assert page.status_code == 200
    done = staff.post('/civ-admin/password_change/', {'old_password': PASSWORD, 'new_password1': NEW, 'new_password2': NEW})
    assert done.status_code == 302
    assert StaffUser.objects.get().check_password(NEW)


def test_insurers_page_is_back_and_permission_groups_are_gone(staff):
    """Owner, 2026-10-22: the Insurers page manages insurers only; no Permission groups page."""
    assert staff.get('/civ-admin/buyers/buyerorg/').status_code == 200
    assert staff.get('/civ-admin/auth/group/').status_code == 404
    menu = staff.get('/civ-admin/').content.decode()
    assert 'Insurers and acquirers' in menu and 'Permission groups' not in menu


def test_the_new_password_must_be_different(company, member_user, signed_in, api):
    signed_in(member_user)
    same = change(api, PASSWORD, PASSWORD)
    assert same.status_code == 400 and same.json()['detail'] == 'Your new password must be different from your current one.'
