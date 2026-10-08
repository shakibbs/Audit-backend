import pytest
from django.contrib.auth.hashers import identify_hasher

from apps.accounts.models import ClientUser
from tests.conftest import PASSWORD


@pytest.mark.django_db
def test_client_user_password_uses_argon2(admin_user):
    assert identify_hasher(admin_user.password).algorithm == 'argon2'
    assert admin_user.check_password(PASSWORD)


@pytest.mark.django_db
def test_user_made_without_password_cannot_sign_in(company):
    user = ClientUser.objects.create_user(client=company, email='New@SunPath.com', name='New')
    assert user.email == 'new@sunpath.com'
    assert not user.has_usable_password()
