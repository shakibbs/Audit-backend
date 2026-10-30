"""Owner, 2026-10-31: plain words for the staff panel's odd messages."""
import pytest
from django.core import mail

from apps.staff.models import StaffUser
from apps.staff.welcome import send_welcome
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


@pytest.fixture
def boss(client):
    user = StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD)
    client.force_login(user)
    return user


def test_empty_list_and_sign_out(client, boss):
    page = client.get('/civ-admin/reports/quoterequest/').content.decode()
    assert 'yielded into' not in page and 'Nothing here yet' in page
    out = client.post('/civ-admin/logout/').content.decode()
    assert 'quality time' not in out and 'You are signed out of the CiV staff panel.' in out


def test_wrong_password_message(client):
    StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD)
    page = client.post('/civ-admin/login/', {'username': 'team@complyiv.com', 'password': 'wrong'}).content.decode()
    assert 'case-sensitive' not in page and 'Wrong email or password. Check both and try again.' in page


def test_a_new_member_is_welcomed_and_an_existing_one_gets_a_new_password_email(client, boss):
    client.post('/civ-admin/staff/staffuser/add/', {'email': 'new@complyiv.com', 'name': 'New'})
    assert mail.outbox[-1].subject == 'Welcome to the CiV team panel'
    send_welcome(boss)
    assert mail.outbox[-1].subject == 'Choose a new password for the CiV staff panel'
