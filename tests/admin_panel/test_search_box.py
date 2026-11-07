"""Owner, 2026-11-07: the staff search box finds companies and people, with the menu's own section names."""
import pytest
from django.core.cache import cache

from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


@pytest.fixture
def boss(client):
    cache.clear()
    client.force_login(StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD))


def test_finds_a_company_and_a_person(client, boss, company, admin_user):
    page = client.get('/civ-admin/search/', {'s': company.name[:6]}).content.decode()
    assert company.name in page and 'Client company' in page
    person = client.get('/civ-admin/search/', {'s': admin_user.email}).content.decode()
    assert admin_user.email in person and f'Person at {company.name}' in person


def test_menu_pages_use_the_menu_section_names(client, boss):
    page = client.get('/civ-admin/search/', {'s': 'client reports'}).content.decode()
    assert 'Client reports' in page and 'Records' in page
