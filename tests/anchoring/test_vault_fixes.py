"""Owner, 2026-10-23: the Vault page's real "Deleted under retention", no "NaN" without a seal, the lookup's link to
the number's own evidence file, and "Verify a file" also recognising reports and evidence files CiV made."""
import hashlib
from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.access_log.recorder import record
from apps.contacts.models import ContactEvent
from apps.keyring.tokens import Tokenizer
from apps.reports.models import Report

pytestmark = pytest.mark.django_db


def test_vault_numbers_are_real(company, admin_user, signed_in, api):
    signed_in(admin_user)
    vault = api.call('get', '/api/vault').json()
    assert vault['deletedUnderRetention'] == 0 and vault['lastAnchor'] is None


def test_the_lookup_links_to_that_numbers_evidence_file(company, admin_user, signed_in, api):
    signed_in(admin_user)
    day = (timezone.now() - timedelta(days=1)).date().isoformat()
    none = api.call('get', f'/api/position?phone=(916) 555-0142&date={day}').json()
    assert none['ref'] is None
    token = Tokenizer(company).token('+19165550142')
    ContactEvent.objects.create(client=company, phone_token=token, phone_token_kid='k1', source_system='twilio', source_record_id='m1',
                                source_grade='C', channel='text', direction='outbound', occurred_at=timezone.now() - timedelta(days=2))
    found = api.call('get', f'/api/position?phone=(916) 555-0142&date={day}').json()
    assert found['ref'] == f'p-{token[:24]}'
    assert api.call('get', f"/api/evidence/{found['ref']}").status_code == 200


def test_verify_a_file_knows_reports_and_evidence_files(company, admin_user, signed_in, api):
    signed_in(admin_user)
    pdf = b'%PDF-1.4 a CiV report'
    sha = hashlib.sha256(pdf).hexdigest()
    Report.objects.create(client=company, name='Period audit report', period=date(2026, 9, 1), status='ready', sha256=sha)
    hit = api.call('get', f'/api/hash-check?hash={sha}').json()
    assert hit['found'] and hit['artifact'] == 'Period audit report · Sep 2026'
    other = hashlib.sha256(b'an evidence file').hexdigest()
    record('evidence_file_downloaded', client_id=company.pk, object=f'(916) •••-0142 · pdf · sha256 {other}')
    assert api.call('get', f'/api/hash-check?hash={other}').json()['artifact'].startswith('Evidence file · (916)')
    assert api.call('get', f"/api/hash-check?hash={'0' * 64}").json()['found'] is False


def test_verify_a_file_knows_files_given_to_civ(company, other_company, admin_user, signed_in, api):
    """Owner, 2026-10-30: uploads, vendor contracts, proof files, staff documents and released packages are found too."""
    from django.utils import timezone as tz
    from apps.documents.models import ClientDocument
    from apps.reports.models import QuoteRequest
    from apps.uploads.models import UploadedFile
    from apps.vendors.models import VendorContract
    signed_in(admin_user)

    def sha(text):
        return hashlib.sha256(text.encode()).hexdigest()

    UploadedFile.objects.create(client=company, source=UploadedFile._meta.get_field('source').choices[0][0], original_name='optouts-sept.csv', sha256=sha('a'))
    VendorContract.objects.create(client=company, key='acme', name='Acme Leads', original_name='acme.pdf', sha256=sha('b'), uploaded_by='Dana')
    ClientDocument.objects.create(client=company, kind='agreement', original_name='msa.pdf', sha256=sha('c'))
    QuoteRequest.objects.create(client=company, name='Litigation evidence package', asked_by='Dana', status='released',
                                package_sha256=sha('d'), released_at=tz.now())
    from apps.provenance.models import ProofRequest
    ProofRequest.objects.create(client=company, batch_key='k', batch_label='Bulk import', batch_size=1, phone_token='ab' * 32,
                                masked_label='(916) •••-0142', due_at=tz.now(), original_name='form.png', file_sha256=sha('f'), answered_at=tz.now())
    UploadedFile.objects.create(client=other_company, source=UploadedFile._meta.get_field('source').choices[0][0], original_name='theirs.csv', sha256=sha('e'))
    check = lambda t: api.call('get', f'/api/hash-check?hash={sha(t)}').json()  # noqa: E731
    assert check('a')['found'] and 'optouts-sept.csv' in check('a')['artifact'] and check('a')['capturedAt']
    assert check('b')['artifact'] == 'Vendor contract · Acme Leads · acme.pdf'
    assert check('c')['artifact'] == 'Document · Service agreement · msa.pdf'
    assert check('d')['artifact'].startswith('Litigation evidence package · released')
    assert check('f')['artifact'] == 'Proof request file · (916) •••-0142 · form.png'
    assert check('e')['found'] is False  # another company's file is never found


def test_the_vault_follows_the_month(company, admin_user, signed_in, api):
    """Owner, 2026-10-30: the month picker — records read and days sealed in that month; the strip ends with it."""
    import uuid
    from datetime import datetime, UTC
    from apps.ledger.models import Fingerprint
    signed_in(admin_user)
    for when in (datetime(2026, 9, 5, tzinfo=UTC), datetime(2026, 9, 9, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC)):
        Fingerprint.objects.create(client=company, job_id=uuid.uuid4(), source_system='vicidial', source_record_id=str(uuid.uuid4()),
                                   content_kind='call', source_grade='B', sha256=uuid.uuid4().hex * 2, fetched_at=when)
    sep = api.call('get', '/api/vault?period=2026-09').json()
    assert sep['artifacts'] == '2' and sep['period'] == 'Sep 2026' and sep['coverage'][-1]['label'] == 'Sep 2026'
    assert api.call('get', '/api/vault').json()['artifacts'] == '3'  # no month: everything held
