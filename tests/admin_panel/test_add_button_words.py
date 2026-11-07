"""Owner, 2026-11-07: "Add a connection" when a tab has none, "Add another connection" after."""
import pytest

from apps.connections.models import Connection, Status
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_add_button_words(client, company, other_company):
    client.force_login(StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD))
    Connection.objects.create(client=other_company, provider='twilio', status=Status.CONNECTED)
    empty = client.get(f'/civ-admin/clients/client/{company.pk}/change/').content.decode()
    assert '<span>Add a connection</span>' in empty and '<span>Add another Connection</span>' not in empty
    one = client.get(f'/civ-admin/clients/client/{other_company.pk}/change/').content.decode()
    assert '<span>Add another connection</span>' in one
