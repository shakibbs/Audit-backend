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
    from django.urls import reverse
    response = client.post(reverse('admin:clients_client_user_password_link', args=[company.pk, user.pk]))  # the Users tab button
    assert response.status_code == 302
    assert mail.outbox[0].to == ['new@sunpath.com']
    # the hidden person and invite pages are switched off (owner, 2026-10-24): only the company's tabs manage people
    for path in ('/civ-admin/accounts/clientuser/', f'/civ-admin/accounts/clientuser/{user.pk}/change/', '/civ-admin/accounts/invite/'):
        assert client.get(path).status_code == 404
