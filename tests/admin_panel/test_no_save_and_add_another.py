"""Owner, 2026-10-24: no "Save and add another" button anywhere in the staff panel."""
import pytest

from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_edit_and_add_pages_have_no_save_and_add_another(client, company):
    staff = StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD)
    client.force_login(staff)
    for path in (f'/civ-admin/clients/client/{company.pk}/change/', '/civ-admin/clients/client/add/',
                 f'/civ-admin/staff/staffuser/{staff.pk}/change/', '/civ-admin/staff/staffuser/add/'):
        page = client.get(path).content.decode()
        assert 'Save and add another' not in page and 'Save and continue editing' in page, path
