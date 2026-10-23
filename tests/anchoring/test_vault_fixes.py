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
