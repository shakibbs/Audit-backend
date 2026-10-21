"""Module 12 step 4 + lead files: uploaded vendor leads count like CRM leads (never as a CRM import); the lead price
from the CRM or the file; dispute candidates inside the contract's window; M30; the CSV for the vendor."""
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.consent.models import ConsentResult
from apps.contacts.models import ContactEvent
from apps.contacts.normalize import codes_for
from apps.imports.creations import price_of
from apps.imports.models import CrmCreation, ImportBatch
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.vendors.disputes import candidates, disputable_value
from apps.vendors.models import VendorContract, VendorLead
from apps.vendors.rates import vendor_rates

pytestmark = pytest.mark.django_db
PHONE = '+19165550142'
n = iter(range(10**6))


@pytest.fixture(autouse=True)
def setup(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    load(RULEBOOK_DIR / 'v3.0.yaml')


def post(api, path, data):
    return api.post(path, data, HTTP_X_CSRFTOKEN=api.cookies['csrftoken'].value)


def bad_call(company, token, when):
    c = ContactEvent.objects.create(client=company, phone_token=token, phone_token_kid='k1', source_system='vicidial', source_record_id=f'c{next(n)}',
                                    source_grade='B', channel='call', direction='outbound', occurred_at=when, masked_label='(916) •••-0142')
    ConsentResult.objects.create(client=company, contact=c, variant='strict', status='no_proof', primary_code='NP_NONE',
                                 evaluation_as_of=when, rulebook_version='3.0')


def contract(company, vendor, days):
    VendorContract.objects.create(client=company, key=vendor.lower(), name=vendor, original_name='t.pdf', sha256='a' * 64,
                                  dispute_days=days, uploaded_by='Dana')


def test_price_is_read_from_the_crm():
    assert price_of('hubspot', json.dumps({'properties': {'lead_cost': '$12.50'}}).encode()) == Decimal('12.50')
    assert price_of('salesforce', json.dumps({'Lead_Price__c': 40}).encode()) == Decimal('40')
    assert price_of('hubspot', json.dumps({'properties': {'cost': 'n/a'}}).encode()) is None


def test_lead_file_upload_counts_for_the_vendor_but_is_never_a_crm_import(company, admin_user, signed_in):
    today = timezone.localdate().isoformat()
    csv = f'phone,vendor,sub_id,received,price,lead_id\n{PHONE},SolarLeads Inc,7,{today},12.50,L-1\n,No Phone Vendor,,{today},1,\n'.encode()
    api = signed_in(admin_user)
    reply = post(api, '/api/uploads', {'source': 'Vendor lead files', 'file': SimpleUploadedFile('leads.csv', csv, content_type='text/csv')}).json()
    assert (reply['rowsRead'], reply['rowsRejected']) == (1, 1)
    lead = VendorLead.objects.get()
    assert (lead.vendor, lead.sub_id, lead.price, lead.lead_ref) == ('SolarLeads Inc', '7', Decimal('12.50'), 'L-1')
    assert lead.phone_token == codes_for(company).token(PHONE) and PHONE not in json.dumps(list(VendorLead.objects.values()), default=str)
    assert {r['key'] for r in vendor_rates(company)} == {'solarleads inc'} and not ImportBatch.objects.exists()
    assert any(s['name'] == 'Vendor lead files' and s['acceptsUpload'] for s in api.get('/api/sources').json())


def test_dispute_candidates_inside_the_window_and_m30(company, admin_user, signed_in):
    now = timezone.now()
    for i, (vendor, age, price) in enumerate([('SolarLeads Inc', 5, Decimal('12.50')), ('SolarLeads Inc', 40, Decimal('9')),
                                              ('SolarLeads Inc', 3, None), ('No Terms Co', 2, Decimal('30'))]):
        CrmCreation.objects.create(client=company, source_system='hubspot', record_id=f'r{i}', created_at=now - timedelta(days=age),
                                   vendor=vendor, phone_tokens=[f't{i}'], price=price)
        bad_call(company, f't{i}', now - timedelta(days=age) + timedelta(hours=1))
    contract(company, 'SolarLeads Inc', 30)
    found = candidates(company, now)
    solar = found['solarleads inc']
    assert [r['lead'] for r in solar['rows']] == ['hubspot:r0', 'hubspot:r2']  # the 40-day-old lead is past the 30 days
    assert (solar['total'], solar['noPrice']) == (Decimal('12.50'), 1) and solar['rows'][0]['result'] == 'No proof'
    assert found['no terms co']['rows'] == [] and found['no terms co']['basis'] == 'no contract on file'
    m30 = disputable_value(company, now)
    assert m30['display'] == '$12.50' and '1 with no price' in m30['note'] and 'no contract on file' in m30['note']
    api = signed_in(admin_user)
    assert api.get('/api/vendor-disputes?vendor=solarleads%20inc').json()['total'] == '12.50'
    text = api.get('/api/vendor-disputes?vendor=SolarLeads%20Inc&csv=1').content.decode()
    assert text.splitlines()[0] == 'lead,vendor,sub_id,date,price,result,reasons,number' and 'no price' in text


TF = 'https://cert.trustedform.com/' + 'a' * 40


def test_the_vendors_consent_link_in_the_lead_file_is_claimed_and_becomes_the_proof(company, admin_user, signed_in, monkeypatch):
    from apps.certificates import claim as claim_module
    from apps.certificates.models import CertificateClaim
    from apps.consent.models import ConsentProof
    from apps.consent.sources import source_of
    seen = []
    monkeypatch.setattr(claim_module, 'match_now', lambda claim, number, token: seen.append((number, token)))
    monkeypatch.setattr('apps.vendors.lead_certificates.match_now', lambda claim, number, token: seen.append((number, token)))
    today = timezone.localdate().isoformat()
    csv = (f'phone,vendor,received,price,lead_id,trustedform_cert_url\n{PHONE},SolarLeads Inc,{today},12.50,L-1,{TF}\n'
           f'+14805550923,SolarLeads Inc,{today},12.50,L-2,\n').encode()
    post(signed_in(admin_user), '/api/uploads', {'source': 'Vendor lead files', 'file': SimpleUploadedFile('leads.csv', csv, content_type='text/csv')})
    claim = CertificateClaim.objects.get()
    assert (claim.provider, claim.cert_ref) == ('trustedform', 'a' * 40)
    token = codes_for(company).token(PHONE)
    assert seen == [(PHONE, token)]  # matched while the number was in memory
    proof = ConsentProof.objects.get()
    assert (proof.phone_token, proof.certificate_id, proof.source_system, proof.lead_id) == (token, claim.pk, 'vendor_lead_file', 'L-1')
    assert source_of(proof) == 'vendor'


def test_lead_file_leads_with_no_proof_get_a_proof_request(company, admin_user, signed_in):
    from apps.provenance.models import ProofRequest
    from apps.provenance.requests import send
    today = timezone.localdate().isoformat()
    csv = f'phone,vendor,received\n{PHONE},SolarLeads Inc,{today}\n'.encode()
    post(signed_in(admin_user), '/api/uploads', {'source': 'Vendor lead files', 'file': SimpleUploadedFile('leads.csv', csv, content_type='text/csv')})
    token = codes_for(company).token(PHONE)
    ContactEvent.objects.create(client=company, phone_token=token, phone_token_kid='k1', source_system='vicidial', source_record_id='c1',
                                source_grade='B', channel='call', direction='outbound', occurred_at=timezone.now(), masked_label='(916) •••-0142')
    assert send(company) == 1
    request = ProofRequest.objects.get()
    assert request.batch_label.startswith('Vendor lead file · 1 lead ·') and request.phone_token == token
    assert send(company) == 0  # asked once per file
