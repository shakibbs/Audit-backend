"""Bug fix 2026-10-23: time zone / region were typed into the hidden "API secret" box and locked; now a visible
setting the readers use (older connections that kept it in the secret still work)."""
import pytest

from apps.connections.models import Connection, Status
from apps.connections.providers import PROVIDERS
from apps.imports.dialer_lists import tool_zone
from apps.sync.connectors.convoso import Convoso

pytestmark = pytest.mark.django_db


def test_tools_ask_for_a_visible_setting_not_a_secret():
    for tool in ('five9', 'convoso', 'genesys', 'vicidial'):
        assert PROVIDERS[tool].setting_label
    assert not PROVIDERS['five9'].secret_label and not PROVIDERS['convoso'].secret_label and not PROVIDERS['genesys'].secret_label


def test_readers_use_the_visible_setting_and_old_connections_still_work(company):
    new = Connection.objects.create(client=company, provider='convoso', status=Status.CONNECTED, setting='America/Chicago')
    new.set_credentials({'key': 't'})
    assert str(Convoso(new).tz) == 'America/Chicago'
    old = Connection.objects.create(client=company, provider='convoso', status=Status.CONNECTED)
    old.set_credentials({'key': 't', 'secret': 'America/Denver'})
    assert str(Convoso(old).tz) == 'America/Denver'
    vici = Connection.objects.create(client=company, provider='vicidial', status=Status.CONNECTED, setting='America/Los_Angeles')
    vici.set_credentials({'key': 'u'})
    assert str(tool_zone(vici)) == 'America/Los_Angeles'


def test_staff_pick_the_time_zone_from_a_list(client, company):
    """Owner, 2026-10-23: a dropdown, not a typed box; a value saved before the list is kept."""
    from apps.staff.models import StaffUser
    from tests.connections.test_connections import connection_row, save_page
    from tests.conftest import PASSWORD
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    page = client.get(f'/civ-admin/clients/client/{company.pk}/change/').content.decode()
    assert 'Eastern — New York' in page and 'mypurecloud.com' in page
    response = save_page(client, company, [connection_row(0, provider='convoso', key='t', setting='America/Chicago')])
    assert response.status_code == 302, response.content.decode()[:800]
    assert Connection.objects.get(client=company).setting == 'America/Chicago'
    assert save_page(client, company, [connection_row(0, provider='convoso', key='t', setting='Mars/Base')]).status_code == 200  # not in the list
