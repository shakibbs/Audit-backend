"""Owner, 2026-10-31: the path at the top never repeats a name, and has a short back link for phones."""
import re

import pytest

from apps.admin_panel.templatetags.civ_path import plain_path
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_a_repeated_name_is_shown_once():
    parts = [{'title': 'Insurers and acquirers', 'link': '/a/'}, {'title': 'insurers and acquirers', 'link': '/a/b/'}, {'title': 'Falcon Risk'}]
    assert plain_path(parts) == [{'title': 'insurers and acquirers', 'link': '/a/b/'}, {'title': 'Falcon Risk'}]


def test_the_page_path(client):
    client.force_login(StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD))
    for url in ('/civ-admin/buyers/buyerorg/', '/civ-admin/regulatory/regchange/'):
        page = client.get(url).content.decode()
        full = page[page.index('civ-path-full'):page.index('civ-path-short')]
        names = [n.strip().lower() for n in re.findall(r'>\s*([^<>]+?)\s*</(?:a|span)\s*>', full) if n.strip() and n.strip() != 'chevron_right']
        assert len(names) == len(set(names)), (url, names)
        assert 'civ-path-short' in page
