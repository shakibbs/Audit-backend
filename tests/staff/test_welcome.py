"""Owner decision 2026-10-22: a new CiV team member is created with name and email only and gets a welcome link (7 days,
once) to choose their own password; a new link cancels the old one; expired or used links do nothing."""
import re
from datetime import timedelta

import pytest
from django.core import mail
from django.test import Client as Browser
from django.utils import timezone

from apps.staff.models import StaffUser, StaffWelcome
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


@pytest.fixture
def boss(client):
    client.force_login(StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD))
    return client


def token() -> str:
    return re.search(r'token=([\w-]+)', mail.outbox[-1].body).group(1)


def test_adding_a_team_member_sends_a_welcome_link_and_they_choose_a_password(boss):
    response = boss.post('/civ-admin/staff/staffuser/add/', {'email': 'Kim@ComplyIV.com', 'name': 'Kim Lee'})
    assert response.status_code == 302, response.content.decode()[:1500]
    kim = StaffUser.objects.get(email='kim@complyiv.com')
    assert not kim.has_usable_password()  # nobody typed a password for Kim
    assert kim.is_superuser  # full access for now (owner, 2026-10-23)
    assert mail.outbox[0].to == ['kim@complyiv.com'] and '/civ-admin/welcome/?token=' in mail.outbox[0].body
    link = token()
    b = Browser()
    assert 'Choose your own password' in b.get(f'/civ-admin/welcome/?token={link}').content.decode()
    short = b.post('/civ-admin/welcome/', {'token': link, 'new_password1': 'short', 'new_password2': 'short'})
    assert short.status_code == 200  # too short: the page shows the problem
    done = b.post('/civ-admin/welcome/', {'token': link, 'new_password1': PASSWORD, 'new_password2': PASSWORD})
    assert done.status_code == 302 and '/civ-admin/login/' in done['Location']
    kim.refresh_from_db()
    assert kim.check_password(PASSWORD) and StaffWelcome.objects.get().used_at
    again = b.post('/civ-admin/welcome/', {'token': link, 'new_password1': 'Another-long-pass-9', 'new_password2': 'Another-long-pass-9'})
    assert again.status_code == 302 and kim.check_password(PASSWORD)  # used once only


def test_a_new_link_cancels_the_old_and_expired_links_fail(boss):
    boss.post('/civ-admin/staff/staffuser/add/', {'email': 'kim@complyiv.com', 'name': 'Kim Lee'})
    first = token()
    kim = StaffUser.objects.get(email='kim@complyiv.com')
    boss.post('/civ-admin/staff/staffuser/', {'action': 'send_welcome_again', '_selected_action': [kim.pk]})
    second = token()
    assert first != second and StaffWelcome.objects.count() == 1
    b = Browser()
    assert b.get(f'/civ-admin/welcome/?token={first}').status_code == 302  # the old link no longer works
    StaffWelcome.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    assert b.get(f'/civ-admin/welcome/?token={second}').status_code == 302  # expired


def test_the_staff_page_has_no_password_code_or_reset_form(boss):
    """Owner, 2026-10-23: nobody types a password for someone else; a button sends a link instead."""
    kim = StaffUser.objects.create(email='kim@complyiv.com', name='Kim Lee')
    page = boss.get(f'/civ-admin/staff/staffuser/{kim.pk}/change/').content.decode()
    assert 'argon2' not in page and 'Reset password' not in page and 'Send password link' in page
    assert boss.get(f'/civ-admin/staff/staffuser/{kim.pk}/password/').status_code == 403
    sent = boss.post(f'/civ-admin/staff/staffuser/{kim.pk}/password-link/')
    assert sent.status_code == 302 and mail.outbox[-1].to == ['kim@complyiv.com']
    assert boss.post(f'/civ-admin/staff/staffuser/{kim.pk}/change/', {'email': 'kim@complyiv.com', 'name': 'Kim L', 'is_active': 'on',
                                                                     'is_superuser': 'on'}).status_code == 302
