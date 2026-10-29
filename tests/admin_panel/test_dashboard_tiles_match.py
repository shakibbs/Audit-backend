"""Owner, 2026-10-30: each Dashboard tile opens a list of exactly what its number counts; deleted companies left out."""
import re

import pytest
from django.utils import timezone

from apps.access_log.recorder import record
from apps.clients.models import Client
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def tiles(page: str) -> dict:
    found = re.findall(r'<a class="kpi-main" href="([^"]+)">\s*<span class="kpi-tag">([^<]+)</span>\s*<span class="kpi-val">(\d+)</span>', page)
    return {tag: (int(value), url.replace('&amp;', '&')) for url, tag, value in found}


def test_tiles_open_what_they_count(client, company, other_company, admin_user, member_user, other_admin):
    Client.objects.filter(pk=other_company.pk).update(deleted_at=timezone.now())  # a deleted company is not counted
    record('sign_in', client_id=company.pk)
    client.force_login(StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD))
    page = client.get('/civ-admin/').content.decode()
    t = tiles(page)
    assert t['Client users'][0] == 2 and 'in 1 companies' in page
    listed = client.get(t['Client users'][1]).content.decode()
    assert company.name in listed and other_company.name not in listed
    assert t['Active clients'][1].endswith('?status__exact=active')
    assert t['Connections working'][1].endswith('?attention=working') and 'failed or stale</a>' in page
    signins, url = t['Sign-ins · 24 h']
    log = client.get(url).content.decode()
    assert signins == 1 and 'within=24h' in url and 'Last 24 hours' in log
