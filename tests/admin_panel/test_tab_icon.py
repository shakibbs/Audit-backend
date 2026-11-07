"""Owner, 2026-11-07: the staff panel's browser tab shows the teal "iV" icon."""
import pytest

from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_the_tab_icon(client):
    assert 'admin_panel/icon.svg' in client.get('/civ-admin/login/').content.decode()
    client.force_login(StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD))
    assert 'admin_panel/icon.svg' in client.get('/civ-admin/').content.decode()
