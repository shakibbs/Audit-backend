"""Who You Contact → click a count to see the phone numbers behind it (owner 2026-11-16)."""
from datetime import timedelta

import pytest

from apps.access_log.models import AccessEntry
from apps.imports.models import CrmCreation
from apps.metrics.who import who_contact
from apps.uploads.models import DncCheck, InternalListEntry, Source
from tests.metrics.test_who import NOW, TODAY, call, upload
from tests.regulatory.test_portal_api import browser_for

pytestmark = pytest.mark.django_db


def setup(company):
    CrmCreation.objects.create(client=company, source_system='hubspot', record_id='contacts:1', created_at=NOW, vendor='Vendor A', phone_tokens=['p1', 'p2', 'p3'])
    for token in ('p1', 'p2', 'p3', 'p4'):
        call(company, token, days_ago=2)
    up = upload(company, Source.DNC_CHECKS)
    DncCheck.objects.create(client=company, upload=up, phone_token='p1', checked_on=TODAY - timedelta(days=5), listed=False, list_name='national')
    InternalListEntry.objects.create(client=company, upload=upload(company, Source.INTERNAL_LIST), phone_token='p2', added_on=TODAY - timedelta(days=20))


def test_a_vendors_unchecked_numbers(company, admin_user):
    setup(company)
    vendor = next(r for r in who_contact(company)['leadSources'] if r['name'] == 'Vendor A')
    assert '_tokens' not in vendor  # the page never carries the numbers themselves
    got = browser_for(admin_user).get(f"/api/who-contact/numbers?source={vendor['id']}&column=national").json()
    assert got['source'] == 'Vendor A' and got['total'] == 2 and len(got['rows']) == 2
    assert got['rows'][0]['number'] == '(916) •••-0001' and got['rows'][0]['why'].startswith('No national')
    assert AccessEntry.objects.filter(action='who_numbers_viewed', object__startswith='Vendor A · national').exists()


def test_all_sources_and_the_internal_list(company, member_user):
    setup(company)
    api = browser_for(member_user)  # every client user may look; only Admins and lawyers change switches
    assert api.get('/api/who-contact/numbers?source=all&column=national').json()['total'] == 3  # p2, p3, p4
    internal = api.get('/api/who-contact/numbers?source=all&column=internal').json()
    assert internal['total'] == 1 and internal['rows'][0]['why'].startswith('On your list since')


def test_bad_requests(company, admin_user):
    api = browser_for(admin_user)
    assert api.get('/api/who-contact/numbers?source=all&column=nope').status_code == 400
    assert api.get('/api/who-contact/numbers?source=ls-unknown&column=national').status_code == 404


def test_switches_say_who_and_when(company, admin_user):
    """Owner, 2026-11-16: a switched-on list shows who switched it on and when; off shows nothing."""
    CrmCreation.objects.create(client=company, source_system='hubspot', record_id='contacts:9', created_at=NOW, vendor='Vendor A', phone_tokens=['p1'])
    api = browser_for(admin_user)
    row = next(r for r in api.get('/api/who-contact').json()['leadSources'] if r['name'] == 'Vendor A')
    assert row['markedBy'] == {'national': None, 'state': None, 'internal': None, 'reassigned': None}
    saved = api.call('patch', f"/api/who-contact/{row['id']}", {'column': 'national', 'checked': True}).json()
    assert saved['markedBy']['national'] == f'Dana Reyes (Admin) · {TODAY:%-d %b %Y}'
    again = next(r for r in api.get('/api/who-contact').json()['leadSources'] if r['name'] == 'Vendor A')
    assert again['markedBy']['national'].startswith('Dana Reyes (Admin)') and again['markedBy']['state'] is None
    off = api.call('patch', f"/api/who-contact/{row['id']}", {'column': 'national', 'checked': False}).json()
    assert off['markedBy']['national'] is None
