"""Owner, 2026-10-31: delete pages name things in plain words, never "StaffWelcome object (4)"."""
import pytest

from apps.clients.models import StatusChange
from apps.staff.models import StaffUser
from apps.staff.welcome import send_welcome
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_delete_page_names_the_password_links(client):
    boss = StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD)
    dana = StaffUser.objects.create_superuser(email='dana@complyiv.com', name='Dana', password=PASSWORD)
    send_welcome(dana)
    client.force_login(boss)
    page = client.get(f'/civ-admin/staff/staffuser/{dana.pk}/delete/').content.decode()
    assert 'Password link for dana@complyiv.com (sent ' in page and 'StaffWelcome object' not in page


def test_a_stage_change_reads_plainly(company):
    change = StatusChange.objects.create(client=company, old_status='trial', new_status='active')
    assert str(change).startswith('Stage change: Trial → Active (')
