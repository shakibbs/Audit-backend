"""The portal's consent views: Contact Ledger results, the number page's consent card, Consent Integrity, certificates."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.certificates.models import CertificateClaim
from apps.consent.checks import check_contact
from apps.consent.keeping import freeze
from apps.consent.models import ConsentProof, ConsentResult, ResultChange
from apps.consent.needs import work_out
from apps.contacts.epochs import epoch_for
from apps.contacts.models import ContactEvent
from apps.optouts.models import OptOutEvent
from apps.rulebook.loader import RULEBOOK_DIR, load
from tests.regulatory.test_portal_api import browser_for

pytestmark = pytest.mark.django_db
NOW = timezone.now().replace(microsecond=0)
n = iter(range(10**6))


@pytest.fixture(autouse=True)
def rulebook():
    return load(RULEBOOK_DIR / 'v3.0.yaml')[0]


def contact(client, at=None, person='a1' * 16, label='(916) •••-0001'):
    at = at or NOW - timedelta(hours=1)
    c = ContactEvent.objects.create(client=client, phone_token=person, phone_token_kid='k1', source_system='convoso', masked_label=label,
                                    source_record_id=f'r{next(n)}', source_grade='C', channel='call', direction='outbound',
                                    occurred_at=at, dial_mode='manual', recipient_state='CA', time_zones=['America/Los_Angeles'],
                                    epoch=epoch_for(client.pk, person, at))
    work_out(c)
    check_contact(c)
    return c


def cert(client, person='a1' * 16, state='claimed', expires=None):
    made = NOW - timedelta(days=2)
    claim = CertificateClaim.objects.create(client=client, provider='trustedform', cert_ref=f'{next(n):040d}', state=state,
                                            deadline_at=made + timedelta(hours=72), cert_created_at=made if state == 'claimed' else None,
                                            cert_expires_at=(expires or NOW + timedelta(days=400)) if state == 'claimed' else None)
    ConsentProof.objects.create(client=client, phone_token=person, epoch=epoch_for(client.pk, person, made), kind='certificate',
                                proof_type='web_cert', certificate=claim, captured_at=made, date_known=state == 'claimed',
                                source_system='salesforce', source_record_id=f'leads:{next(n)}')
    return claim


def test_the_ledger_shows_each_calls_result_reason_and_checks(company, member_user):
    cert(company)
    good = contact(company)
    bad = contact(company, person='b2' * 16, label='(916) •••-0002')
    api = browser_for(member_user)
    rows = {r['id']: r for r in api.get('/api/contacts').json()}
    g, b = rows[f'ce-{good.pk}'], rows[f'ce-{bad.pk}']
    assert (g['status'], g['code'], g['checks'][:3]) == ('VERIFIED', 'VF_OK', ['pass', 'pass', 'not_measured'])
    assert g['proof'].startswith('TrustedForm certificate') and 'dnc_unknown' in g['bases']
    assert (b['status'], b['code'], b['checks'][0]) == ('NO_PROOF', 'NP_NONE', 'fails') and 'No proof' in b['reasonText']
    assert [r['id'] for r in api.get('/api/contacts?status=NO_PROOF').json()] == [f'ce-{bad.pk}']
    assert api.get('/api/contacts?status=NOT_CHECKED').json() == []


def test_the_number_page_has_the_consent_card_history_and_opt_outs(company, member_user):
    cert(company)
    c = contact(company)
    ResultChange.objects.create(client=company, contact=c, variant='strict', old_status='pending', new_status='verified', reason='certificate_read')
    OptOutEvent.objects.create(client=company, phone_token=c.phone_token, at=NOW, channel='text', method='keyword', source_system='twilio', source_record_id='SM1')
    api = browser_for(member_user)
    ref = api.get('/api/contacts').json()[0]['phoneE164']
    page = api.get(f'/api/evidence/{ref}').json()
    assert page['worstStatus'] == 'VERIFIED' and page['counts'] == {'VERIFIED': 1}
    card = page['consent']
    assert card['proofs'][0]['provider'] == 'TrustedForm' and card['proofs'][0]['usedBy'] == 1  # calls that used it
    assert {x['basis']: x['status'] for x in card['needs']} == {'dnc_unknown': 'VERIFIED'}
    assert card['history'][0] == {**card['history'][0], 'from': 'PENDING', 'to': 'VERIFIED', 'reason': 'certificate read'}
    assert len(card['notMeasured']) == 5 and card['draftRules'] is True
    assert page['optOuts'][0]['channel'] == 'text'


def test_pending_and_frozen_are_left_out_of_the_standing_and_totals(company, member_user):
    cert(company, state='waiting')
    pending = contact(company)
    frozen = contact(company, person='a1' * 16)
    freeze(ConsentResult.objects.filter(contact=frozen), 'FZ_SOURCE_DELETED')
    api = browser_for(member_user)
    ref = api.get('/api/contacts').json()[0]['phoneE164']
    page = api.get(f'/api/evidence/{ref}').json()
    assert page['worstStatus'] == 'PENDING' and page['consent']['frozen'] == 1
    summary = api.get('/api/consent').json()
    assert summary['contacts'] == 0 and summary['pending'] == 1 and summary['frozen'] == 1 and pending


def test_consent_integrity_summary_is_real(company, member_user):
    cert(company)
    contact(company)  # verified
    contact(company, person='b2' * 16)  # no proof
    other = ConsentProof.objects.create(client=company, phone_token='c3' * 16, kind='self_asserted', proof_type='crm_flag',
                                        epoch=epoch_for(company.pk, 'c3' * 16, NOW - timedelta(days=3)),
                                        captured_at=NOW - timedelta(days=3), source_system='hubspot', source_record_id='contacts:1')
    contact(company, person=other.phone_token)  # self-asserted
    s = browser_for(member_user).get('/api/consent').json()
    assert s['contacts'] == 3 and {m['status']: m['count'] for m in s['mix']} == {'VERIFIED': 1, 'WEAK': 0, 'CONFLICTING': 0, 'NO_PROOF': 2}
    assert {r['code'] for r in s['reasons']} == {'NP_NONE', 'NP_SELF_ASSERTED'} and s['dncUnknownShare'] == 100
    assert s['certificatePairs'] == 1 and s['certificateValidity'] == 100 and len(s['trend']) == 4 and s['real'] is True
    assert s['expiring'][-1] == {'within': '90 days', 'count': 0}


def test_certificates_list_with_state_and_use(company, member_user):
    cert(company)
    cert(company, state='lost')
    contact(company)
    rows = browser_for(member_user).get('/api/certificates').json()
    assert sorted((r['stateLabel'], r['usedBy']) for r in rows) == [('Claimed', 1), ('Lost: not claimed in time', 0)]  # the good one wins
    assert all(r['ref'].endswith('…') and len(r['ref']) == 9 for r in rows)  # never the whole certificate ID


def test_each_client_sees_only_its_own(company, other_company, member_user, other_admin):
    cert(company)
    contact(company)
    assert browser_for(other_admin).get('/api/consent').json()['contacts'] == 0
    assert browser_for(other_admin).get('/api/certificates').json() == []
    assert browser_for(other_admin).get('/api/contacts').json() == []
