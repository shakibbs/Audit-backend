"""Owner, 2026-10-24: deleting a client company hides it and switches it off; every record and file is kept, staff can
open it again (read-only) from the "Deleted companies" filter and Restore it."""
import pytest

from apps.access_log.models import AccessEntry
from apps.accounts.models import ClientUser
from apps.buyers.models import BuyerLink, BuyerOrg
from apps.clients.models import Client
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(client):
    client.force_login(StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD))
    return client


def test_delete_hides_switches_off_and_keeps_everything_then_restore(staff, company, admin_user):
    org = BuyerOrg.objects.create(name='Falcon Risk', domain='falconrisk.com')
    link = BuyerLink.objects.create(org=org, client=company, granted_by='Dana')
    page = staff.get(f'/civ-admin/clients/client/{company.pk}/delete/').content.decode()
    assert 'Every record and file is kept' in page
    assert staff.post(f'/civ-admin/clients/client/{company.pk}/delete/', {'post': 'yes'}).status_code == 302
    company.refresh_from_db()
    assert company.deleted_at and not company.is_active and not company.can_sync
    assert ClientUser.objects.filter(client=company).count() == 1  # nothing erased
    row = f'/civ-admin/clients/client/{company.pk}/change/'
    assert row not in staff.get('/civ-admin/clients/client/').content.decode()  # hidden from the list
    assert row in staff.get('/civ-admin/clients/client/?deleted=yes').content.decode()
    view = staff.get(f'/civ-admin/clients/client/{company.pk}/change/')
    assert view.status_code == 200 and 'name="name"' not in view.content.decode()  # read-only
    link.refresh_from_db()
    assert not link.active(company.start_date)  # the insurer loses access
    assert AccessEntry.objects.filter(action='client_deleted', client_id=company.pk).exists()
    staff.post('/civ-admin/clients/client/?deleted=yes', {'action': 'restore', '_selected_action': [company.pk]})
    company.refresh_from_db()
    assert company.deleted_at is None and company.is_active
    assert AccessEntry.objects.filter(action='client_restored', client_id=company.pk).exists()


def test_people_of_a_deleted_company_cannot_sign_in(staff, company, admin_user, api):
    staff.post(f'/civ-admin/clients/client/{company.pk}/delete/', {'post': 'yes'})
    reply = api.call('post', '/api/session/sign-in', {'email': admin_user.email, 'password': PASSWORD})
    assert reply.status_code == 400 and Client.objects.filter(pk=company.pk).exists()
