"""Owner, 2026-10-30: wrong passwords lock the computer that typed them, not the person; 50 from all computers lock the
email everywhere and the person gets one warning email."""
import pytest
from django.core import mail
from django.test import Client as Browser

from apps.access_log.models import AccessEntry
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db
STRANGER, OWN = '93.184.216.34', '93.184.216.99'


def portal(ip, email, password):
    return Browser(REMOTE_ADDR=ip).post('/api/session/sign-in', {'email': email, 'password': password}, content_type='application/json')


def staff(browser, password):
    return browser.post('/civ-admin/login/?next=/civ-admin/', {'username': 'team@complyiv.com', 'password': password})


def test_a_stranger_cannot_lock_the_real_person_out(admin_user):
    for _ in range(5):
        portal(STRANGER, admin_user.email, 'wrong')
    assert portal(STRANGER, admin_user.email, PASSWORD).status_code == 429  # the guessing computer is locked
    assert portal(OWN, admin_user.email, PASSWORD).status_code == 200  # the person, on their own computer, is not


def test_fifty_tries_from_many_computers_lock_everywhere_and_warn_once(admin_user):
    for n in range(50):
        portal(f'93.184.{n}.1', admin_user.email, 'wrong')
    assert portal(OWN, admin_user.email, PASSWORD).status_code == 429
    portal(OWN, admin_user.email, PASSWORD)
    warned = [m for m in mail.outbox if m.to == [admin_user.email]]
    assert len(warned) == 1 and 'locked for 15 minutes' in warned[0].body
    assert AccessEntry.objects.filter(action='account_locked_everywhere', object=admin_user.email).count() == 1


def test_the_staff_panel_follows_the_same_rule():
    StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD)
    stranger = Browser(REMOTE_ADDR=STRANGER)
    for _ in range(5):
        staff(stranger, 'wrong')
    assert 'Too many wrong tries' in staff(stranger, PASSWORD).content.decode()
    assert staff(Browser(REMOTE_ADDR=OWN), PASSWORD).status_code == 302
    for n in range(45):
        staff(Browser(REMOTE_ADDR=f'93.184.{n}.1'), 'wrong')
    assert 'Too many wrong tries' in staff(Browser(REMOTE_ADDR=OWN), PASSWORD).content.decode()
    assert any(m.to == ['team@complyiv.com'] and 'staff panel' in m.body for m in mail.outbox)
