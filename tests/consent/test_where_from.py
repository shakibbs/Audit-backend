"""Module 7 step 1: where a certificate came from, who holds it, and fingerprint-only proof once it no longer opens."""
import json
from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from apps.certificates.models import CertificateClaim
from apps.connections.models import Connection, Status
from apps.consent.checks import check_contact
from apps.consent.keeping import mark_gone, run_rechecks
from apps.consent.models import ConsentProof, ConsentResult
from apps.consent.needs import work_out
from apps.consent.proofs import proofs_seen
from apps.consent.sources import custody_of, source_of
from apps.consent.words import check_states
from apps.contacts.epochs import epoch_for
from apps.contacts.models import ContactEvent
from apps.imports.batches import rebuild
from apps.imports.creations import creation_seen
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.sync.connector import Record

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 10, 6, 16, 0, tzinfo=UTC)
n = iter(range(10**6))


@pytest.fixture(autouse=True)
def rulebook():
    load(RULEBOOK_DIR / 'v3.0.yaml')


def cert_link():
    return 'https://cert.trustedform.com/' + f'{next(n):040x}'


def seen(company, provider, rid, row, kind='crm_record'):
    """A synced record carrying a certificate; returns the proof it made."""
    conn = Connection.objects.get_or_create(client=company, provider=provider, defaults={'status': Status.CONNECTED})[0]
    ref = row['_link'].rsplit('/', 1)[-1]
    CertificateClaim.objects.create(client=company, provider='trustedform', cert_ref=ref, deadline_at=T0 + timedelta(hours=72))
    raw = json.dumps(row).encode()
    proofs_seen(company, conn, Record(rid, raw, kind, T0), ['p1'])
    return ConsentProof.objects.get(source_record_id=rid)


def test_hubspot_says_whether_it_came_from_the_clients_form_an_upload_or_a_vendor(company):
    for how, expected in (('FORM', 'client_form'), ('IMPORT', 'uploaded_list'), ('INTEGRATION', 'vendor'), ('CRM_UI', 'unknown')):
        proof = seen(company, 'hubspot', f'contacts:{how}', {'id': how, '_link': cert_link(), 'properties': {'hs_object_source': how}})
        assert source_of(proof) == expected, how


def test_salesforce_web_lead_is_the_clients_form_an_uploaded_list_is_a_vendor(company):
    web = seen(company, 'salesforce', 'leads:00Q1', {'Id': '00Q1', 'LeadSource': 'Web', '_link': cert_link()}, kind='lead')
    assert source_of(web) == 'client_form'
    conn = Connection.objects.get(client=company, provider='salesforce')
    for i in range(30):  # a list uploaded in one burst by one user
        row = {'Id': f'00QL{i}', 'CreatedDate': (T0 + timedelta(seconds=i)).strftime('%Y-%m-%dT%H:%M:%S.000+0000'), 'CreatedById': '005U',
               'LeadSource': 'Web'}
        creation_seen(company, conn, Record(f'leads:00QL{i}', json.dumps(row).encode(), 'lead', T0), [f't{i}'])
    rebuild(company)
    listed = seen(company, 'salesforce', 'leads:00QL3', {'Id': '00QL3', 'LeadSource': 'Web', '_link': cert_link()}, kind='lead')
    assert source_of(listed) == 'uploaded_list'  # the upload pattern wins over what the record says


def test_a_dialer_record_is_source_unknown_never_guessed(company):
    proof = seen(company, 'convoso', 'call-1', {'id': 'call-1', '_link': cert_link()}, kind='call')
    assert source_of(proof) == 'unknown'


def test_who_holds_each_certificate(company):
    def claim(state, error=''):
        return CertificateClaim.objects.create(client=company, provider='trustedform', cert_ref=f'{next(n):040x}', state=state,
                                               deadline_at=T0, last_error=error)
    assert custody_of(claim('claimed')) == 'claimed'
    assert custody_of(claim('lost')) == 'lost'
    assert custody_of(claim('lost', 'NotFound')) == 'not_found'


def contact_with_cert(company, expires):
    claim = CertificateClaim.objects.create(client=company, provider='trustedform', cert_ref=f'{next(n):040x}', state='claimed',
                                            deadline_at=T0, cert_created_at=T0 - timedelta(days=2), cert_expires_at=expires)
    ConsentProof.objects.create(client=company, phone_token='p1', epoch=epoch_for(company.pk, 'p1', T0 - timedelta(days=2)), kind='certificate',
                                proof_type='web_cert', certificate=claim, captured_at=T0 - timedelta(days=2), source_system='hubspot',
                                source_record_id='contacts:1')
    c = ContactEvent.objects.create(client=company, phone_token='p1', phone_token_kid='k1', source_system='convoso', source_record_id='c1',
                                    source_grade='C', channel='call', direction='outbound', occurred_at=T0, dial_mode='manual',
                                    epoch=epoch_for(company.pk, 'p1', T0))
    work_out(c)
    return claim, c


def test_a_certificate_that_no_longer_opens_is_fingerprint_only_proof(company):
    claim, c = contact_with_cert(company, expires=T0 + timedelta(days=60))
    check_contact(c, as_of=T0 + timedelta(days=61))  # checked after it stopped opening
    r = ConsentResult.objects.get(contact=c, variant='strict')
    assert (r.status, r.primary_code) == ('weak', 'WK_FINGERPRINT_ONLY')
    assert check_states(r)[:2] == ['pass', 'gap']


def test_the_nightly_run_marks_expired_certificates_gone_and_rechecks(company):
    claim, c = contact_with_cert(company, expires=timezone.now() - timedelta(days=1))
    ConsentResult.objects.filter(contact=c).delete()
    check_contact(c, as_of=timezone.now() - timedelta(days=5))  # first checked while it still opened
    assert mark_gone() == 1
    claim.refresh_from_db()
    assert claim.gone_at == claim.cert_expires_at
    run_rechecks()
    r = ConsentResult.objects.get(contact=c, variant='strict')
    assert (r.primary_code, r.reeval_reason) == ('WK_FINGERPRINT_ONLY', 'time_passed')
    assert mark_gone() == 0  # once
