"""Certificates: found in synced records, claimed first and fast, kept only as facts, lost honestly when too late."""
import io
import json
import urllib.error
from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from apps.access_log.models import AccessEntry
from apps.certificates import claim as claims
from apps.certificates import vendors
from apps.certificates.models import CertificateClaim
from apps.certificates.scan import found_in, scan_record
from apps.connections import testers
from apps.connections.models import Connection, Status
from apps.ledger.models import Fingerprint
from apps.sync.connector import Record
from apps.tenancy.scope import _scope

pytestmark = pytest.mark.django_db
CERT = '2b1f6e0c' + 'a' * 32
TOKEN = 'A1B2C3D4-1111-2222-3333-444455556666'
TF_ANSWER = {'outcome': 'success', 'retain': {'results': {'expires_at': '2027-01-01T12:00:00Z'}},
             'insights': {'properties': {'created_at': '2026-10-01T15:02:11Z', 'page_url': 'https://sunpath.example/quote?phone=9165550001&email=a@b.c'}}}


def lead(raw: dict, at=None) -> Record:
    return Record('L1', json.dumps(raw).encode(), 'lead', at or timezone.now(), [])


@pytest.fixture
def trustedform(company):
    c = Connection(client=company, provider='trustedform', status=Status.CONNECTED)
    c.set_credentials({'key': 'tf-key'})
    c.save()
    return c


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def vendor_answers(monkeypatch, answer=None, status=200):
    sent = []

    def urlopen(request, timeout):
        sent.append(request)
        if status != 200:
            raise urllib.error.HTTPError(request.full_url, status, 'x', {}, io.BytesIO(b'{}'))
        return Reply(json.dumps(answer).encode())
    monkeypatch.setattr(vendors.urllib.request, 'urlopen', urlopen)
    return sent


def test_links_and_tokens_are_found_in_any_record():
    raw = json.dumps({'trustedform_cert_url': f'https://cert.trustedform.com/{CERT}', 'leadid_token': TOKEN.lower(), 'other_id': TOKEN}).encode()
    assert found_in(raw) == [('trustedform', CERT), ('jornaya', TOKEN)]
    assert found_in(b'xxTrustedFormCertUrl=https%3A//nothing') == []
    assert found_in(json.dumps({'session_uuid': TOKEN}).encode()) == []  # a UUID in another field is not a Jornaya token


def test_a_lead_with_a_certificate_is_queued_once_with_a_72_hour_deadline(company):
    at = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)
    scan_record(company, None, lead({'cert': f'https://cert.trustedform.com/{CERT}'}, at), [])
    scan_record(company, None, lead({'cert': f'https://cert.trustedform.com/{CERT}'}, at), [])
    claim = CertificateClaim.objects.get()
    assert claim.state == 'waiting' and claim.deadline_at == at + timedelta(hours=72)


def test_claimed_quickly_facts_kept_personal_details_not(company, trustedform, monkeypatch):
    sent = vendor_answers(monkeypatch, TF_ANSWER)
    scan_record(company, None, lead({'cert': f'https://cert.trustedform.com/{CERT}'}), [])
    assert claims.claim_due() == 1
    claim = CertificateClaim.objects.get()
    assert claim.state == 'claimed' and claim.claimed_at
    assert claim.cert_created_at == datetime(2026, 10, 1, 15, 2, 11, tzinfo=UTC) and claim.cert_expires_at.year == 2027
    assert claim.page == 'sunpath.example/quote'  # no query string: it held the phone and email
    request = sent[0]
    assert request.full_url == f'https://cert.trustedform.com/{CERT}' and request.get_method() == 'POST'
    assert request.headers['Api-version'] == '4.0' and 'retain' in json.loads(request.data)
    fp = Fingerprint.objects.get(source_system='trustedform')
    assert fp.content_kind == 'certificate' and fp.source_grade == 'B'
    assert '9165550001' not in json.dumps(list(CertificateClaim.objects.values()), default=str)


def test_nearest_deadline_first(company, trustedform, monkeypatch):
    order = []
    monkeypatch.setattr(vendors, 'claim_trustedform', lambda ref, key, reference: order.append(ref) or vendors.Facts(b'{}', None, None, ''))
    now = timezone.now()
    for i, hours in enumerate([60, 5, 30]):
        CertificateClaim.objects.create(client=company, provider='trustedform', cert_ref=f'{i:040d}', deadline_at=now + timedelta(hours=hours))
    claims.claim_due()
    assert order == [f'{1:040d}', f'{2:040d}', f'{0:040d}']


def test_vendor_down_is_retried_until_the_deadline_then_lost(company, trustedform, monkeypatch):
    vendor_answers(monkeypatch, status=503)
    claim = CertificateClaim.objects.create(client=company, provider='trustedform', cert_ref=CERT, deadline_at=timezone.now() + timedelta(hours=1))
    claims.claim_due()
    claim.refresh_from_db()
    assert claim.state == 'waiting' and claim.attempts == 1 and claim.last_error == 'HTTPError'
    CertificateClaim.objects.filter(pk=claim.pk).update(deadline_at=timezone.now() - timedelta(minutes=1))
    claims.claim_due()
    claim.refresh_from_db()
    assert claim.state == 'lost' and AccessEntry.objects.filter(action='certificate_lost').exists()


def test_an_expired_certificate_is_lost_at_once(company, trustedform, monkeypatch):
    vendor_answers(monkeypatch, status=404)
    CertificateClaim.objects.create(client=company, provider='trustedform', cert_ref=CERT, deadline_at=timezone.now() + timedelta(hours=5))
    claims.claim_due()
    assert CertificateClaim.objects.get().state == 'lost'


def test_no_key_waits_and_a_key_added_in_time_still_works(company, monkeypatch):
    vendor_answers(monkeypatch, TF_ANSWER)
    CertificateClaim.objects.create(client=company, provider='trustedform', cert_ref=CERT, deadline_at=timezone.now() + timedelta(hours=20))
    claims.claim_due()
    assert CertificateClaim.objects.get().state == 'no_key'
    c = Connection(client=company, provider='trustedform', status=Status.CONNECTED)
    c.set_credentials({'key': 'tf-key'})
    c.save()
    claims.claim_due()
    assert CertificateClaim.objects.get().state == 'claimed'


def test_alert_12_hours_before_the_deadline_once(company):
    CertificateClaim.objects.create(client=company, provider='trustedform', cert_ref=CERT, deadline_at=timezone.now() + timedelta(hours=10))
    claims.warn_close_deadlines()
    claims.warn_close_deadlines()
    assert AccessEntry.objects.filter(action='certificate_deadline_close').count() == 1


def test_jornaya_lookup(company, monkeypatch):
    sent = vendor_answers(monkeypatch, {'authentic': 1, 'creation_time': '2026-10-01T15:00:00Z', 'url': 'https://form.example/a?x=1'})
    c = Connection(client=company, provider='jornaya', status=Status.CONNECTED)
    c.set_credentials({'account': 'LAC1', 'key': 'jk'})
    c.save()
    CertificateClaim.objects.create(client=company, provider='jornaya', cert_ref=TOKEN, deadline_at=timezone.now() + timedelta(hours=20))
    claims.claim_due()
    claim = CertificateClaim.objects.get()
    assert claim.state == 'claimed' and claim.page == 'form.example/a' and 'lac=LAC1' in sent[0].full_url


def test_claims_are_locked_per_client(company, other_company):
    CertificateClaim.objects.create(client=company, provider='trustedform', cert_ref=CERT, deadline_at=timezone.now())
    CertificateClaim.objects.create(client=other_company, provider='trustedform', cert_ref=CERT, deadline_at=timezone.now())
    with _scope('client', str(company.pk)):
        assert list(CertificateClaim.objects.values_list('client_id', flat=True)) == [company.pk]


def test_the_test_buttons(monkeypatch):
    vendor_answers(monkeypatch, status=404)
    assert testers.test_trustedform({'key': 'k'})[0] == Status.CONNECTED
    vendor_answers(monkeypatch, status=401)
    assert testers.test_trustedform({'key': 'bad'})[0] == Status.FAILED
    assert testers.test_jornaya({'key': 'k'})[0] == Status.FAILED  # no account code


def test_every_synced_record_is_checked_for_certificates():
    from apps.sync import handoff
    assert scan_record in handoff.RECEIVERS
