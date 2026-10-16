"""Module 3 made visible: Sync column and Certificates tile in the admin; real Source Registry and Data health API."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.certificates.models import CertificateClaim
from apps.connections.models import Connection, Status
from apps.staff.models import StaffUser
from apps.sync.models import SyncCursor
from tests.conftest import PASSWORD
from tests.regulatory.test_portal_api import browser_for

pytestmark = pytest.mark.django_db


@pytest.fixture
def tools(company):
    live = Connection.objects.create(client=company, provider='convoso', status=Status.CONNECTED)
    stale = Connection.objects.create(client=company, provider='five9', status=Status.STALE)
    waiting = Connection.objects.create(client=company, provider='salesforce', status=Status.WAITING)
    later = Connection.objects.create(client=company, provider='pipedrive', status=Status.UNTESTED)
    now = timezone.now()
    SyncCursor.objects.create(client=company, connection=live, source_system='convoso', last_heartbeat_at=now - timedelta(minutes=2),
                              last_event_at=now - timedelta(minutes=2), records_delivered=48210)
    SyncCursor.objects.create(client=company, connection=stale, source_system='five9', last_heartbeat_at=now - timedelta(hours=3),
                              records_delivered=9120, last_error='Five9Error', failures_in_row=4)
    return live, stale, waiting, later


@pytest.fixture
def staff(client):
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    return client


def test_admin_connections_show_sync_and_the_client_page_shows_certificates(staff, company, tools):
    for state, n in (('claimed', 3), ('waiting', 1), ('lost', 2)):
        for i in range(n):
            CertificateClaim.objects.create(client=company, provider='trustedform', cert_ref=f'{state}{i}', deadline_at=timezone.now(), state=state)
    page = staff.get(f'/civ-admin/clients/client/{company.pk}/change/').content.decode()
    assert 'Live' in page and '48,210 records read' in page
    assert 'Stale' in page and 'problem: Five9Error (4× in a row)' in page
    assert 'waiting for the client to click Allow' in page
    assert 'its adapter comes when a client needs it' in page
    assert 'Certificates' in page and 'claimed · 1 waiting · 0 no key · 2 lost' in page


def test_source_registry_lists_real_tools_and_keeps_the_upload_types(company, tools, member_user):
    rows = {r['name']: r for r in browser_for(member_user).get('/api/sources').json()}
    assert rows['Convoso']['status'] == 'current' and 'every 2 minutes' in rows['Convoso']['access']
    assert rows['Five9']['status'] == 'stale' and 'every 10 minutes' in rows['Five9']['access']
    assert rows['Salesforce']['status'] == 'not_supplied' and rows['Salesforce']['blocks'] == 'Waiting for you to click Allow'
    assert rows['Pipedrive']['blocks'].startswith('Not read yet')
    uploads = [n for n, r in rows.items() if r['acceptsUpload']]
    assert uploads == ['Internal do-not-contact list', 'Policies, training, contracts', 'Complaint log', 'DNC check records', 'Reassigned-number query logs']


def test_data_health_is_real_and_honest_about_what_is_not_measured(company, tools, member_user, other_admin):
    company.access_level = 1
    company.save()
    data = browser_for(member_user).get('/api/data-health').json()
    assert data['accessLevel'] == 1 and data['sources'] == {'live': 1, 'stale': 1, 'notSupplied': 2, 'total': 4}
    assert data['recordsCompleteness'] is None and data['conversationReview'] is None and data['lastChangeAt']
    other = browser_for(other_admin).get('/api/data-health').json()  # another company sees only its own (nothing)
    assert other['sources']['total'] == 0 and other['lastChangeAt'] is None


def test_records_completeness_box(company, member_user):
    from datetime import date

    from apps.reconcile.models import PeriodIntegrity, Reconciliation
    api = browser_for(member_user)
    assert api.get('/api/data-health').json()['completenessStatus'] == 'not_measured'
    month = PeriodIntegrity.objects.create(client=company, period=date(2026, 9, 1), completeness=None)
    data = api.get('/api/data-health').json()
    assert data['completenessStatus'] == 'not_available' and 'No billing source' in data['completenessNote']
    Reconciliation.objects.create(client=company, period=date(2026, 9, 1), measure='texts', source_system='twilio', records=700,
                                  independent_total=1000, ratio=0.7, flagged=True)
    PeriodIntegrity.objects.filter(pk=month.pk).update(completeness=0.7, incomplete=True)
    data = api.get('/api/data-health').json()
    assert (data['recordsCompleteness'], data['completenessStatus']) == (0.7, 'incomplete')
    assert data['completenessNote'] == 'CiV received only 70% of the texts Twilio billed · September 2026'
    PeriodIntegrity.objects.filter(pk=month.pk).update(completeness=0.912, incomplete=False)
    assert api.get('/api/data-health').json()['completenessNote'] == 'Your logs compared with what Twilio billed · September 2026'
