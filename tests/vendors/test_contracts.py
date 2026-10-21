"""Module 12 step 3: the client uploads vendor contracts (private, logged, kept 4 years); M07 = active vendors with an
unexpired contract on file; the 12 draft clauses are in the Rulebook."""
from datetime import UTC, date, datetime, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.access_log.models import AccessEntry
from apps.imports.models import CrmCreation
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.rulebook.lookup import RuleSet
from apps.vendors.contracts import purge_old, terms_on_file
from apps.vendors.models import VendorContract

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def setup(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    load(RULEBOOK_DIR / 'v3.0.yaml')


def leads(company, *vendors):
    for i, v in enumerate(vendors):
        CrmCreation.objects.create(client=company, source_system='hubspot', record_id=f'{v}{i}', created_at=timezone.now() - timedelta(days=5),
                                   vendor=v, phone_tokens=[f't{i}'])


def upload(api, vendor, ends='2027-12-31', days='30', name='contract.pdf'):
    token = api.cookies['csrftoken'].value
    return api.post('/api/vendor-contracts', {'vendor': vendor, 'endsOn': ends, 'disputeDays': days,
                                              'file': SimpleUploadedFile(name, b'%PDF-1.4 terms', content_type='application/pdf')},
                    HTTP_X_CSRFTOKEN=token)


def test_the_twelve_draft_clauses_five_required():
    clauses = RuleSet().get('vendor_required_clauses', on=date(2026, 10, 22)).value
    assert len(clauses) == 12 and [c['id'] for c in clauses if c['required']] == ['consent', 'certificate', 'proof_on_request', 'optouts_passed', 'indemnity']


def test_m07_is_not_measured_until_contracts_are_supplied(company):
    leads(company, 'SolarLeads Inc')
    assert terms_on_file(company)['notMeasured'] == 'Contracts not supplied'


def test_upload_counts_unexpired_contracts(company, admin_user, signed_in):
    leads(company, 'SolarLeads Inc', 'Vendor E', 'Old Vendor')
    api = signed_in(admin_user)
    made = upload(api, 'solarleads inc').json()  # spelling differences are the same vendor
    assert made['state'] == 'on_file' and made['disputeDays'] == 30 and made['url']
    upload(api, 'Old Vendor', ends='2025-01-31')
    m07 = terms_on_file(company)
    assert (m07['value'], m07['display']) == (33.3, '33.3%') and 'clauses not checked yet' in m07['note']
    file = api.get(made['url'])
    assert file.status_code == 200 and 'no-store' in file['Cache-Control']
    assert {'vendor_contract_added', 'vendor_contract_opened'} <= set(AccessEntry.objects.values_list('action', flat=True))


def test_members_cannot_upload_and_bad_files_are_refused(company, admin_user, member_user, signed_in):
    assert upload(signed_in(member_user), 'Vendor E').status_code == 403
    assert upload(signed_in(admin_user), 'Vendor E', name='run.exe').status_code == 400


def test_files_go_after_four_years(company, admin_user, signed_in):
    upload(signed_in(admin_user), 'Vendor E')
    VendorContract.objects.update(uploaded_at=timezone.now() - timedelta(days=4 * 365 + 1))
    assert purge_old() == 1
    c = VendorContract.objects.get()
    assert c.purged_at and not c.file and c.sha256


def test_the_contract_list(company, admin_user, signed_in):
    api = signed_in(admin_user)
    upload(api, 'A Brand New Vendor')  # no leads from it yet: still accepted
    rows = api.get('/api/vendor-contracts').json()
    assert [r['vendor'] for r in rows] == ['A Brand New Vendor'] and rows[0]['state'] == 'on_file'
