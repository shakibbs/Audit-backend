"""Owner, 2026-10-30: when a staff member changes their own password, a password link still in their email stops working."""
import re

import pytest
from django.core import mail

from apps.access_log.models import AccessEntry
from apps.staff.models import StaffUser
from apps.staff.welcome import send_welcome
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db
NEW = 'Another-long-pass-99'


def test_an_old_link_stops_working(client):
    user = StaffUser.objects.create_superuser(email='new@complyiv.com', name='New', password=PASSWORD)
    send_welcome(user)
    link = re.search(r'(/civ-admin/welcome/\?token=[\w-]+)', mail.outbox[-1].body).group(1)
    client.force_login(user)
    done = client.post('/civ-admin/password_change/', {'old_password': PASSWORD, 'new_password1': NEW, 'new_password2': NEW})
    assert done.status_code == 302
    assert not user.welcomes.filter(used_at__isnull=True).exists()
    assert 'password link(s) closed' in AccessEntry.objects.get(action='password_changed').object
    client.logout()
    opened = client.get(link, follow=True).content.decode()
    assert 'expired or was already used' in opened
    user.refresh_from_db()
    assert user.check_password(NEW)
