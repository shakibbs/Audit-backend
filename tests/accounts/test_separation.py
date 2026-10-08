"""CiV staff and client users use separate doors; neither opens the other."""
import pytest

from apps.staff.models import StaffUser
from tests.conftest import PASSWORD


@pytest.fixture
def staff():
    return StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD)


@pytest.mark.django_db
def test_staff_login_does_not_count_in_client_api(client, staff):
    client.force_login(staff)
    assert client.get('/civ-admin/').status_code == 200
    assert client.get('/api/session').json() == {'signedIn': False}
    assert client.post('/api/session/sign-out', content_type='application/json').status_code == 401


@pytest.mark.django_db
def test_staff_credentials_do_not_work_in_client_sign_in(api, staff):
    response = api.call('post', '/api/session/sign-in', {'email': staff.email, 'password': PASSWORD})
    assert response.status_code == 400


@pytest.mark.django_db
def test_client_user_cannot_open_admin_panel(client, signed_in, admin_user):
    api = signed_in(admin_user)
    assert api.get('/civ-admin/').status_code == 302
    assert not client.login(email=admin_user.email, password=PASSWORD)
