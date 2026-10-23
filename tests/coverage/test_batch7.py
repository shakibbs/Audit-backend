"""Card coverage, batch 7: number-page proof elements, vault position lookup and hash check, Rulebook snapshot PDF,
insurer attestation rows."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.anchoring.models import MerkleAnchor
from apps.consent.models import ConsentResult
from apps.contacts.epochs import epoch_for
from apps.contacts.models import ContactEvent
from apps.contacts.normalize import codes_for
from apps.ledger.models import Fingerprint
from apps.optouts.models import OptOutEvent
from apps.rulebook.loader import RULEBOOK_DIR, load
from tests.regulatory.test_portal_api import browser_for

pytestmark = pytest.mark.django_db
NOW = timezone.now().replace(microsecond=0)
PHONE = '+19165550142'


@pytest.fixture
def number(company):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    token = codes_for(company).token(PHONE)
    c = ContactEvent.objects.create(client=company, phone_token=token, phone_token_kid='k1', source_system='convoso', source_record_id='call-1',
                                    source_grade='C', channel='call', direction='outbound', occurred_at=NOW - timedelta(days=2), dial_mode='manual',
                                    masked_label='(916) •••-0142', epoch=epoch_for(company.pk, token, NOW))
    ConsentResult.objects.create(client=company, contact=c, variant='strict', status='verified', primary_code='VF_OK', evaluation_as_of=NOW, rulebook_version='3.0')
    anchor = MerkleAnchor.objects.create(client=company, day=(NOW - timedelta(days=1)).date(), leaf_count=1, root='a' * 64)
    Fingerprint.objects.create(client=company, job_id='00000000-0000-0000-0000-000000000001', source_system='convoso', source_record_id='call-1',
                               content_kind='call', source_grade='C', sha256='e' * 64, fetched_at=NOW - timedelta(days=2), anchor=anchor)
    OptOutEvent.objects.create(client=company, phone_token=token, at=NOW - timedelta(days=1), channel='text', method='keyword',
                               source_system='twilio', source_record_id='SM1')
    return c


def test_the_number_page_has_its_eight_proof_elements(number, member_user):
    api = browser_for(member_user)
    ref = api.get('/api/contacts').json()[0]['phoneE164']
    elements = {e['number']: e for e in api.get(f'/api/evidence/{ref}').json()['proofElements']}
    assert len(elements) == 8 and elements[1]['present'] is True
    assert (elements[5]['present'], elements[5]['tier'], elements[5]['hash']) == (True, 3, 'e' * 64)
    assert elements[3]['present'] is False and elements[8]['present'] is None  # no certificate · no query logs: not measured


def test_position_lookup_on_a_date_never_stores_the_number(number, member_user):
    api = browser_for(member_user)
    day = (NOW - timedelta(days=2)).date().isoformat()
    data = api.get(f'/api/position?phone=(916) 555-0142&date={day}').json()
    rows = {r['label']: r['value'] for r in data['rows']}
    assert data['phone'] == '(916) •••-0142' and rows['Phone epoch'].startswith('Owner 1')
    assert rows['Opt-out history'] == 'None on any channel at that date' and rows['Consent status'] == 'VERIFIED · VF_OK'
    later = {r['label']: r['value'] for r in api.get(f'/api/position?phone=9165550142&date={NOW.date()}').json()['rows']}
    assert later['Opt-out history'].endswith((NOW - timedelta(days=1)).strftime('on %d %b %Y'))  # the STOP the day after the call
    assert api.get(f'/api/position?phone=12&date={day}').status_code == 400


def test_hash_check_finds_a_sealed_fingerprint(number, member_user):
    api = browser_for(member_user)
    hit = api.get(f"/api/hash-check?hash={'e' * 64}").json()
    assert hit['found'] and hit['anchoredOn'] == (NOW - timedelta(days=1)).date().isoformat() and hit['tier'] == 3
    assert api.get(f"/api/hash-check?hash={'0' * 64}").json()['found'] is False


def test_rulebook_snapshot_is_a_pdf(number, member_user):
    reply = browser_for(member_user).get('/api/rulebook/snapshot?period=2026-10')
    assert reply.status_code == 200 and reply['Content-Type'] == 'application/pdf' and reply.content.startswith(b'%PDF')


def test_attestation_rows_from_records(number, member_user):
    data = browser_for(member_user).get('/api/insureds/own').json()
    assert data['contactsPerMonth'] == 1 and data['consentProof'] == 1.0 and data['contactsAfterOptOut'] == 0
    assert data['controls'] == {'policy': None, 'trainingCurrency': None, 'optOutTests90d': None, 'fingerprinted': 1}
    assert data['prerecordedShare'] is None  # not known from this dialer: not measured


def test_the_number_page_says_who_holds_the_consent_proof(number, member_user):
    """Owner, 2026-10-23: the third-party proof row shows who holds the original."""
    from apps.certificates.models import CertificateClaim
    from apps.consent.models import ConsentProof
    claim = CertificateClaim.objects.create(client=number.client, provider='trustedform', cert_ref='abc123', deadline_at=NOW + timedelta(days=3),
                                            state='claimed')
    ConsentProof.objects.create(client=number.client, phone_token=number.phone_token, epoch=number.epoch, kind='certificate', proof_type='web_cert',
                                certificate=claim, captured_at=NOW - timedelta(days=5), source_system='twilio', source_record_id='lead-1')
    api = browser_for(member_user)
    ref = api.get('/api/contacts').json()[0]['phoneE164']
    elements = {e['number']: e for e in api.get(f'/api/evidence/{ref}').json()['proofElements']}
    assert elements[3]['holder'] == "Claimed in the client's account"
