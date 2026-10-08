import pytest
from django.core import mail

from apps.accounts.models import ClientUser
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD


@pytest.mark.django_db
def test_staff_sends_a_password_link_from_admin(client, company):
    staff = StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD)
    user = ClientUser.objects.create_user(client=company, email='new@sunpath.com', name='New')
    client.force_login(staff)
    response = client.post('/civ-admin/accounts/clientuser/', {'action': 'send_password_link', '_selected_action': [user.pk]})
    assert response.status_code == 302
    assert mail.outbox[0].to == ['new@sunpath.com']
