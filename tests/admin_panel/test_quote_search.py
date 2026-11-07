"""Owner, 2026-11-07: a search made only of quote marks finds nothing; names with an apostrophe still work."""
from datetime import date

import pytest

from apps.clients.models import Client
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_quote_marks_alone_find_nothing(client, company, other_company):
    Client.objects.create(name="Joe's Solar", industry='solar', start_date=date(2026, 9, 1))
    client.force_login(StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD))
    for q in ("'", "''", '"', "' '"):
        page = client.get('/civ-admin/clients/client/', {'q': q}).content.decode()
        assert company.name not in page and other_company.name not in page, q
    page = client.get('/civ-admin/clients/client/', {'q': "Joe's Solar"}).content.decode()
    assert "Joe&#x27;s Solar" in page and company.name not in page
