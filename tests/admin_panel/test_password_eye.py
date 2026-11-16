"""Owner, 2026-11-16: every staff password box has an eye button (civ.js) that shows or hides the password."""
import pytest
from django.contrib.staticfiles import finders

from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_the_script_adds_the_eye():
    script = open(finders.find('admin_panel/civ.js')).read()
    assert 'civPasswordEyes' in script and 'input[type="password"]' in script
    assert '.civ-pw-eye' in open(finders.find('admin_panel/civ.css')).read()


def test_password_pages_load_the_script(client):
    login = client.get('/civ-admin/login/').content.decode()
    assert 'type="password"' in login and 'admin_panel/civ.js' in login
    client.force_login(StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD))
    change = client.get('/civ-admin/password_change/').content.decode()
    assert 'type="password"' in change and 'admin_panel/civ.js' in change
