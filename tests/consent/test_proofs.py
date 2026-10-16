"""Collecting proofs: certificates, CRM consent fields and existing customers, each tied to a number and its owner."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from apps.certificates.models import CertificateClaim
from apps.connections.models import Connection, Status
from apps.consent.models import ConsentProof
from apps.consent.proofs import evidence_folder, proofs_seen, refresh_certificate_dates
from apps.contacts.epochs import epoch_for, split
from apps.contacts.models import PhoneEpoch
from apps.imports.batches import rebuild
from apps.imports.creations import creation_seen
from apps.sync import handoff
from apps.sync.connector import Record
from apps.tenancy.scope import _scope

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
CERT = 'https://cert.trustedform.com/' + 'a' * 40


def conn(company, provider):
    return Connection.objects.get_or_create(client=company, provider=provider, defaults={'status': Status.CONNECTED})[0]


def deliver(company, provider, rid, row, kind='lead', at=T0, tokens=('tok1',)):
    handoff.deliver(company, conn(company, provider), Record(rid, json.dumps(row).encode(), kind, at), list(tokens))


def test_the_receiver_is_plugged_in_after_the_certificate_queue():
    from apps.certificates.scan import scan_record
    names = [r.__name__ for r in handoff.RECEIVERS]
    assert names.index('proofs_seen') > names.index(scan_record.__name__)


def test_a_lead_with_a_trustedform_link_becomes_a_proof_for_that_number_and_owner(company):
    deliver(company, 'salesforce', 'leads:00Q1', {'Id': '00Q1', 'TrustedForm_URL__c': CERT})
    proof = ConsentProof.objects.get()
    assert (proof.kind, proof.proof_type, proof.phone_token, proof.lead_id) == ('certificate', 'web_cert', 'tok1', '00Q1')
    assert proof.certificate == CertificateClaim.objects.get() and proof.epoch == PhoneEpoch.objects.get(phone_token='tok1')
    assert not proof.date_known and proof.when() == T0  # the record's time stands in until the certificate is read


def test_a_claimed_certificate_gives_the_proof_its_real_date(company):
    deliver(company, 'salesforce', 'leads:00Q1', {'Id': '00Q1', 'TrustedForm_URL__c': CERT}, at=T0 + timedelta(hours=2))
    CertificateClaim.objects.update(state='claimed', cert_created_at=T0)
    assert refresh_certificate_dates() == 1
    proof = ConsentProof.objects.get()
    assert proof.date_known and proof.captured_at == T0 and proof.when() == T0


def test_the_same_record_read_twice_makes_one_proof(company):
    for _ in range(2):
        deliver(company, 'salesforce', 'leads:00Q1', {'Id': '00Q1', 'TrustedForm_URL__c': CERT})
    assert ConsentProof.objects.count() == 1


def test_a_crm_consent_box_is_stored_as_self_asserted(company):
    deliver(company, 'salesforce', 'leads:00Q2', {'Id': '00Q2', 'TCPA_Consent__c': True, 'Consent_Revoked__c': False})
    deliver(company, 'hubspot', 'contacts:7', {'id': '7', 'properties': {'consent_to_call': 'yes'}}, kind='crm_record', tokens=['tok2'])
    deliver(company, 'salesforce', 'leads:00Q3', {'Id': '00Q3', 'TCPA_Consent__c': False}, tokens=['tok3'])
    assert sorted(ConsentProof.objects.values_list('phone_token', 'kind', 'proof_type')) == [
        ('tok1', 'self_asserted', 'crm_flag'), ('tok2', 'self_asserted', 'crm_flag')]


def test_a_hubspot_customer_date_is_an_existing_customer_proof(company):
    since = T0 - timedelta(days=200)
    deliver(company, 'hubspot', 'contacts:8', {'id': '8', 'properties': {'lifecyclestage': 'customer',
             'hs_lifecyclestage_customer_date': since.isoformat().replace('+00:00', 'Z')}}, kind='crm_record')
    proof = ConsentProof.objects.get()
    assert (proof.kind, proof.proof_type, proof.captured_at) == ('ebr_purchase', 'purchase', since)


def test_a_logged_call_is_not_a_consent_record(company):
    deliver(company, 'hubspot', 'calls:9', {'id': '9', 'properties': {'consent_to_call': 'yes'}}, kind='crm_record')
    assert not ConsentProof.objects.exists()


def test_a_number_from_an_uploaded_list_with_nothing_else_is_no_evidence_found(company):
    hubspot = conn(company, 'hubspot')
    for n in range(30):
        row = {'id': str(n), 'properties': {'createdate': (T0 + timedelta(seconds=n)).isoformat().replace('+00:00', 'Z'),
                                            'hs_object_source': 'IMPORT', 'hs_created_by_user_id': '77'}}
        creation_seen(company, hubspot, Record(f'contacts:{n}', json.dumps(row).encode(), 'crm_record', T0), [f'up{n}'])
    rebuild(company)
    epoch = epoch_for(company.pk, 'up3', T0 + timedelta(days=1))
    from apps.contacts.models import ContactEvent
    ContactEvent.objects.create(client=company, phone_token='up3', phone_token_kid='k1', source_system='convoso', source_record_id='c1',
                                source_grade='B', channel='call', direction='outbound', occurred_at=T0 + timedelta(days=1), epoch=epoch)
    folder = evidence_folder(company, 'up3', epoch)
    assert folder['proofs'] == [] and folder['import_batch'].kind == 'bulk_import' and folder['manual_import_no_evidence']


def test_a_certificate_for_owner_1_does_not_count_for_owner_2(company):
    deliver(company, 'salesforce', 'leads:00Q1', {'Id': '00Q1', 'TrustedForm_URL__c': CERT})
    owner2 = split(company.pk, 'tok1', T0 + timedelta(days=30), PhoneEpoch.Reason.CRM_MOVED)
    assert evidence_folder(company, 'tok1', owner2)['proofs'] == []
    owner1 = PhoneEpoch.objects.get(phone_token='tok1', number=1)
    assert len(evidence_folder(company, 'tok1', owner1)['proofs']) == 1


def test_proofs_are_locked_per_client(company, other_company):
    for client in (company, other_company):
        deliver(client, 'salesforce', 'leads:00Q2', {'Id': '00Q2', 'TCPA_Consent__c': True})
    with _scope('client', str(company.pk)):
        assert set(ConsentProof.objects.values_list('client_id', flat=True)) == {company.pk}


def test_no_numbers_no_proof(company):
    proofs_seen(company, conn(company, 'salesforce'), Record('leads:x', b'{"TCPA_Consent__c": true}', 'lead', T0), [])
    assert not ConsentProof.objects.exists()
