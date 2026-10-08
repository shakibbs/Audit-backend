import pytest

from apps.staff.models import StaffUser
from tests.conftest import PASSWORD


@pytest.mark.django_db
def test_dashboard_shows_numbers_and_tables(client, admin_user):
    staff = StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD)
    client.force_login(staff)
    page = client.get('/civ-admin/').content.decode()
    assert 'Active clients' in page and 'Client companies' in page
    assert 'SunPath Residential Solar' in page
