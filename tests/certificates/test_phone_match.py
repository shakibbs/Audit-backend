"""Module 7 step 2: phone match. The lead's phone is checked against what was typed into the form while it is still
in memory; it is never stored. No answer = not measured; a "no" = conflicting."""
import json
from datetime import timedelta

import pytest
from django.db import connection as db
from django.utils import timezone

from apps.certificates import vendors
from apps.certificates.models import CertificateClaim
from apps.certificates.scan import scan_record
from apps.consent.checks import check_contact
from apps.consent.models import ConsentProof, ConsentResult, Recheck
from apps.consent.needs import work_out
from apps.contacts.epochs import epoch_for
from apps.contacts.models import ContactEvent
from apps.contacts.normalize import codes_for
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.sync.connector import Record
from tests.certificates.test_claims import CERT, TF_ANSWER, trustedform, vendor_answers  # noqa: F401

pytestmark = pytest.mark.django_db
PHONE = '(916) 555-0001'


def lead_with_cert(phone=PHONE, kind='lead', rid='leads:00Q1'):
    raw = {'Id': '00Q1', 'Phone': phone, 'TrustedForm_URL__c': f'https://cert.trustedform.com/{CERT}'}
    return Record(rid, json.dumps(raw).encode(), kind, timezone.now(), [phone])


def answer(match):
    return {**TF_ANSWER, 'match_lead': {'result': {'phone_match': match}}}


def test_the_claim_asks_trustedform_about_the_phone_and_keeps_only_yes_or_no(company, trustedform, monkeypatch):
    sent = vendor_answers(monkeypatch, answer(False))
    scan_record(company, trustedform, lead_with_cert(), [])
    body = json.loads(sent[0].data)
    assert body['match_lead'] == {'phone': '9165550001'} and 'retain' in body  # one request: claim + match
    claim = CertificateClaim.objects.get()
    token = codes_for(company).token(PHONE)
    assert claim.state == 'claimed' and claim.phone_match == {token: False}
    with db.cursor() as cur:  # the number is never stored anywhere
        for table in ('certificate_claim', 'consent_proof', 'fingerprint'):
            cur.execute(f'SELECT * FROM {table}')
            assert '5550001' not in repr(cur.fetchall())


def test_an_already_claimed_certificate_is_matched_on_its_own(company, trustedform, monkeypatch):
    CertificateClaim.objects.create(client=company, provider='trustedform', cert_ref=CERT, state='claimed', deadline_at=timezone.now())
    sent = vendor_answers(monkeypatch, {'match_lead': {'result': {'phone_match': True}}})
    scan_record(company, trustedform, lead_with_cert(), [])
    assert list(json.loads(sent[0].data)) == ['match_lead']
    assert list(CertificateClaim.objects.get().phone_match.values()) == [True]
    assert Recheck.objects.filter(reason='new_proof').exists()  # results for that number are checked again


def test_provider_down_means_not_measured_and_the_claim_is_retried_later(company, trustedform, monkeypatch):
    vendor_answers(monkeypatch, status=503)
    scan_record(company, trustedform, lead_with_cert(), [])
    claim = CertificateClaim.objects.get()
    assert claim.state == 'waiting' and claim.phone_match == {}


def test_dialer_records_are_not_matched(company, trustedform, monkeypatch):
    sent = vendor_answers(monkeypatch, answer(True))
    scan_record(company, trustedform, lead_with_cert(kind='call', rid='call-1'), [])
    assert sent == [] and CertificateClaim.objects.get().state == 'waiting'


def test_jornaya_matching_is_to_confirm(company):
    assert not hasattr(vendors, 'match_jornaya')


@pytest.fixture
def checked(company):
    load(RULEBOOK_DIR / 'v3.0.yaml')

    def run(match):
        token = codes_for(company).token(PHONE)
        now = timezone.now()
        claim = CertificateClaim.objects.create(client=company, provider='trustedform', cert_ref=f'{len(str(match)):040d}', state='claimed',
                                                deadline_at=now, cert_created_at=now - timedelta(days=2), cert_expires_at=now + timedelta(days=400),
                                                phone_match={} if match is None else {token: match})
        ConsentProof.objects.create(client=company, phone_token=token, epoch=epoch_for(company.pk, token, now - timedelta(days=2)),
                                    kind='certificate', proof_type='web_cert', certificate=claim, captured_at=now - timedelta(days=2),
                                    source_system='salesforce', source_record_id=f'leads:{match}')
        c = ContactEvent.objects.create(client=company, phone_token=token, phone_token_kid='k1', source_system='convoso', source_record_id=f'c{match}',
                                        source_grade='C', channel='call', direction='outbound', occurred_at=now - timedelta(hours=1),
                                        dial_mode='manual', epoch=epoch_for(company.pk, token, now))
        work_out(c)
        check_contact(c)
        result = ConsentResult.objects.get(contact=c, variant='strict')
        ConsentProof.objects.all().delete()
        return result
    return run


def test_a_phone_that_does_not_match_is_conflicting(checked):
    r = checked(False)
    assert (r.status, r.primary_code) == ('conflicting', 'CF_PHONE_MISMATCH')


def test_a_match_passes_and_is_no_longer_not_measured(checked):
    r = checked(True)
    assert r.status == 'verified' and 'not_measured:phone_match' not in r.labels


def test_no_answer_never_makes_it_worse(checked):
    r = checked(None)
    assert r.status == 'verified' and 'not_measured:phone_match' in r.labels
