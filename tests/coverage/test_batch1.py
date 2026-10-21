"""Card coverage, batch 1: access log, ledger category / tiers / fingerprint, one contact, internal-list check, vault
numbers, settings facts and agreements, Annex C date, insurer reconciliation, feeds domains."""
from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.access_log.recorder import record
from apps.anchoring.models import MerkleAnchor
from apps.connections.models import Connection, Status
from apps.consent.needs import work_out
from apps.contacts.epochs import epoch_for
from apps.contacts.models import ContactEvent
from apps.documents.models import ClientDocument
from apps.ledger.models import Fingerprint
from apps.optouts.models import OptOutEvent
from apps.reconcile.models import PeriodIntegrity, Reconciliation
from apps.rulebook.loader import RULEBOOK_DIR, load
from tests.regulatory.test_portal_api import browser_for

pytestmark = pytest.mark.django_db
NOW = timezone.now().replace(microsecond=0)
TOKEN = 'ab' * 12 + 'c' * 40


@pytest.fixture
def call(company):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    c = ContactEvent.objects.create(client=company, phone_token=TOKEN, phone_token_kid='k1', source_system='convoso', source_record_id='call-1',
                                    source_grade='C', channel='call', direction='outbound', occurred_at=NOW - timedelta(hours=1),
                                    masked_label='(916) •••-0001', recipient_state='CA', epoch=epoch_for(company.pk, TOKEN, NOW))
    work_out(c)
    Fingerprint.objects.create(client=company, job_id='00000000-0000-0000-0000-000000000001', source_system='convoso', source_record_id='call-1',
                               content_kind='call', source_grade='C', sha256='f' * 64, fetched_at=NOW)
    return c


def test_access_log_shows_the_companys_own_entries(company, member_user, other_company):
    record('sign_in', actor_kind='client_user', actor_id=member_user.pk, actor_label=member_user.email, client_id=company.pk)
    record('proof_reviewed', actor_kind='staff', actor_id=1, actor_label='team@complyiv.com', client_id=company.pk, object='(916) •••-0001')
    record('sign_in', actor_kind='client_user', actor_id=999, client_id=other_company.pk)
    rows = browser_for(member_user).get('/api/access-log').json()
    pairs = [(r['actor'], r['action']) for r in rows]
    assert ('CiV team', 'Proof checked') in pairs and pairs.count(('Sam Lee', 'Signed in')) == 2  # recorded + this test's sign-in
    assert all(r['actor'] in ('CiV team', 'Sam Lee') for r in rows)  # never another company's entries


def test_ledger_rows_have_real_category_tier_and_fingerprint_and_one_contact_opens(call, member_user):
    api = browser_for(member_user)
    row = api.get('/api/contacts').json()[0]
    assert (row['category'], row['tiers'], row['hash']) == ('Marketing', [3], 'f' * 64)
    assert api.get(f"/api/contacts/{row['id']}").json()['id'] == row['id']
    assert api.get('/api/contacts/ce-999999').status_code == 404


def test_the_number_page_checks_the_internal_list(call, company, member_user):
    OptOutEvent.objects.create(client=company, phone_token=TOKEN, at=NOW - timedelta(days=2), channel='text', method='keyword',
                               source_system='twilio', source_record_id='SM1')
    api = browser_for(member_user)
    ref = api.get('/api/contacts').json()[0]['phoneE164']
    checks = api.get(f'/api/evidence/{ref}').json()['listChecks']
    assert checks[0]['list'] == 'Internal do-not-contact list' and checks[0]['onList'] is True and checks[1]['onList'] is None


def test_vault_numbers_are_real(call, company, member_user):
    MerkleAnchor.objects.create(client=company, day=NOW.date() - timedelta(days=1), leaf_count=1, root='a' * 64)
    vault = browser_for(member_user).get('/api/vault').json()
    assert (vault['artifacts'], vault['anchors'], vault['lastAnchor']) == ('1', 1, (NOW.date() - timedelta(days=1)).isoformat())
    assert vault['coverage'][0]['state'] in ('before', 'covered', 'partial') and 'deletedUnderRetention' not in vault  # sample keeps it


def test_settings_facts_and_agreements_and_annex_c(call, company, member_user):
    ClientDocument.objects.create(client=company, kind='annex_c', signed_on=date(2026, 9, 1), title='Annex C')
    api = browser_for(member_user)
    settings = api.get('/api/settings').json()
    assert settings['company']['name'] == company.name and settings['company']['states'] == ['CA'] and 'forum' not in settings['company']
    assert {a['name']: a['status'] for a in settings['agreements']}['Annex C · test opt-outs'] == 'signed'
    assert api.get('/api/revocation').json()['authorisation'] == {'signedOn': '2026-09-01'}


def test_insurer_page_gets_real_completeness_and_reconciliation(company, member_user):
    month = PeriodIntegrity.objects.create(client=company, period=NOW.date().replace(day=1), completeness=0.94, incomplete=False)
    Reconciliation.objects.create(client=company, period=month.period, measure='texts', source_system='twilio', method='bill', records=990,
                                  independent_total=1000, ratio=0.99)
    data = browser_for(member_user).get('/api/insureds/sunpath').json()
    assert data['completeness'] == 0.94
    assert data['reconciliation'] == [{'label': 'Texts in Twilio logs', 'against': 'Messages billed by Twilio', 'records': '990', 'total': '1,000',
                                       'ratio': 0.99, 'result': 'consistent', 'source': 'Billing API · source grade B'}]


def test_sources_say_which_domains_they_feed(company, member_user):
    Connection.objects.create(client=company, provider='twilio', status=Status.CONNECTED)
    row = next(r for r in browser_for(member_user).get('/api/sources').json() if r['id'].startswith('conn-'))
    assert 'SMS' in row['feeds'] and 'REV' in row['feeds']
