"""Owner, 2026-11-07: the Consent pages and Legal holds tabs stay after a save with an error, and say so when empty."""
import re

import pytest

from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def browser_post(page: str) -> dict:
    """What a browser sends back: every hidden and filled field of the page's form (enough for this check)."""
    data = {}
    for name, value in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', page):
        data.setdefault(name, value)
    return data


def test_tabs_stay_after_an_error_and_say_when_empty(client, company):
    client.force_login(StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD))
    url = f'/civ-admin/clients/client/{company.pk}/change/'
    page = client.get(url).content.decode()
    assert 'No consent pages yet.' in page and 'No legal holds.' in page
    data = browser_post(page)
    data.update({'name': '', 'industry': 'Solar', 'plan': 'growth', 'start_date': '2026-10-01', 'status': company.status})  # no name: an error
    again = client.post(url, data).content.decode()
    assert 'This field is required' in again or 'errornote' in again
    assert 'Consent pages' in again and 'No consent pages yet.' in again and 'Legal holds' in again
