"""Module 8 step 1: where each contacted number came from, strongest source first."""
import json
from datetime import UTC, date, datetime, timedelta

import pytest

from apps.certificates.models import CertificateClaim
from apps.connections.models import Connection, Status
from apps.consent.models import ConsentProof
from apps.contacts.epochs import epoch_for
from apps.contacts.models import ContactEvent
from apps.imports.batches import rebuild as rebuild_batches
from apps.imports.creations import creation_seen, vendor_of
from apps.imports.models import CrmCreation
from apps.provenance.ladder import rebuild, untraced
from apps.provenance.models import Provenance
from apps.sync.connector import Record
from apps.tenancy.scope import _scope

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 10, 6, 16, 0, tzinfo=UTC)
n = iter(range(10**6))


def call(client, token, at=T0, label='(916) •••-0001'):
    return ContactEvent.objects.create(client=client, phone_token=token, phone_token_kid='k1', source_system='convoso', masked_label=label,
                                       source_record_id=f'c{next(n)}', source_grade='C', channel='call', direction='outbound',
                                       occurred_at=at, epoch=epoch_for(client.pk, token, at))


def lead(client, token, at, vendor='', rid=None, provider='salesforce'):
    return CrmCreation.objects.create(client=client, source_system=provider, record_id=rid or f'leads:{next(n)}', created_at=at,
                                      phone_tokens=[token], vendor=vendor)


def found(client, token):
    rebuild(client)
    return Provenance.objects.get(client=client, phone_token=token)


def test_the_crm_names_the_vendor(company):
    lead(company, 'p1', T0 - timedelta(days=1), vendor='SolarLeads Inc', rid='leads:00Q1')
    call(company, 'p1')
    p = found(company, 'p1')
    assert (p.basis, p.source_name, p.lead_record_id) == ('crm_field', 'SolarLeads Inc', 'leads:00Q1')


def test_vendor_names_are_read_from_any_vendor_field_and_categories_are_ignored():
    assert vendor_of('salesforce', json.dumps({'LeadSource': 'Web', 'Lead_Vendor__c': '  SOLAR   LEADS - CA '}).encode()) == 'SOLAR LEADS - CA'
    assert vendor_of('hubspot', json.dumps({'properties': {'hs_analytics_source': 'ORGANIC_SEARCH', 'lead_provider': 'BestDeals'}}).encode()) == 'BestDeals'
    assert vendor_of('salesforce', json.dumps({'LeadSource': 'Purchased List'}).encode()) == ''


def test_only_a_certificate_gives_its_website(company):
    claim = CertificateClaim.objects.create(client=company, provider='trustedform', cert_ref='a' * 40, state='claimed', deadline_at=T0,
                                            page='www.home-energy-match.example/form')
    ConsentProof.objects.create(client=company, phone_token='p1', epoch=epoch_for(company.pk, 'p1', T0 - timedelta(days=2)), kind='certificate',
                                proof_type='web_cert', certificate=claim, captured_at=T0 - timedelta(days=2), source_system='convoso', source_record_id='c0')
    call(company, 'p1')
    p = found(company, 'p1')
    assert (p.basis, p.source_name, p.own_website) == ('cert_domain', 'home-energy-match.example', False)


def test_a_number_from_an_uploaded_list(company):
    conn = Connection.objects.create(client=company, provider='salesforce', status=Status.CONNECTED)
    for i in range(25):
        row = {'Id': f'00Q{i}', 'CreatedDate': (T0 - timedelta(days=3, seconds=-i)).strftime('%Y-%m-%dT%H:%M:%S.000+0000'), 'CreatedById': '005U'}
        creation_seen(company, conn, Record(f'leads:00Q{i}', json.dumps(row).encode(), 'lead', T0), [f'u{i}'])
    rebuild_batches(company)
    call(company, 'u3')
    p = found(company, 'u3')
    assert p.basis == 'manual_import' and p.source_name.startswith('Bulk import') and p.batch is not None


def test_nothing_matches_is_untraced_and_listed_monthly(company):
    lead(company, 'p9', T0 - timedelta(days=1), rid='leads:00Q9')
    call(company, 'p9', label='(850) •••-0009')
    p = found(company, 'p9')
    assert p.basis == 'untraced' and 'names no vendor' in p.note
    rows = untraced(company, date(2026, 10, 1), date(2026, 10, 31))
    assert rows == [{'number': '(850) •••-0009', 'firstContactAt': T0, 'tool': 'convoso', 'crmRecord': 'salesforce leads:00Q9',
                     'note': 'The CRM record names no vendor and carries no certificate.'}]


def test_the_latest_lead_before_the_first_call_counts_not_a_later_one(company):
    lead(company, 'p1', T0 - timedelta(days=5), vendor='Early Vendor')
    lead(company, 'p1', T0 - timedelta(days=1), vendor='Right Vendor')
    lead(company, 'p1', T0 + timedelta(days=3), vendor='Too Late Vendor')
    call(company, 'p1')
    call(company, 'p1', at=T0 + timedelta(days=4))
    assert found(company, 'p1').source_name == 'Right Vendor'


def test_inbound_and_test_calls_are_not_traced_and_rows_are_locked(company, other_company):
    c = call(company, 'p1')
    ContactEvent.objects.filter(pk=c.pk).update(direction='inbound')
    assert rebuild(company) == 0
    for client in (company, other_company):
        call(client, 'p2')
        rebuild(client)
    with _scope('client', str(company.pk)):
        assert set(Provenance.objects.values_list('client_id', flat=True)) == {company.pk}
