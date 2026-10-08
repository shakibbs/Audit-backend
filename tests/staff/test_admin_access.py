import pytest
from django.contrib.auth.hashers import identify_hasher

from apps.staff.models import StaffUser

PASSWORD = 'a-long-test-password-1'


@pytest.fixture
def staff():
    return StaffUser.objects.create_superuser(email='Team@ComplyIV.com', name='Team', password=PASSWORD)


@pytest.mark.django_db
def test_staff_signs_in_to_admin_panel(client, staff):
    assert client.login(email='team@complyiv.com', password=PASSWORD)
    assert client.get('/civ-admin/').status_code == 200


@pytest.mark.django_db
def test_admin_panel_needs_sign_in(client):
    response = client.get('/civ-admin/')
    assert response.status_code == 302
    assert '/civ-admin/login/' in response['Location']


@pytest.mark.django_db
def test_turned_off_staff_cannot_sign_in(client, staff):
    staff.is_active = False
    staff.save()
    assert not client.login(email='team@complyiv.com', password=PASSWORD)


@pytest.mark.django_db
def test_new_passwords_use_argon2(staff):
    assert identify_hasher(staff.password).algorithm == 'argon2'


@pytest.mark.django_db
def test_bcrypt_password_is_accepted_and_upgraded(staff):
    from django.contrib.auth.hashers import make_password
    staff.password = make_password(PASSWORD, hasher='bcrypt_sha256')
    staff.save()
    assert staff.check_password(PASSWORD)
    staff.refresh_from_db()
    assert identify_hasher(staff.password).algorithm == 'argon2'
