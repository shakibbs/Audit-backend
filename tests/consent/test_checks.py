"""The five checks: every call and text gets Verified, Weak, Conflicting, No proof (or Pending), with its reasons."""
from datetime import UTC, datetime, timedelta

import pytest

from apps.certificates.models import CertificateClaim
from apps.consent.checks import check_contact
from apps.consent.models import ConsentProof, ConsentResult
from apps.consent.needs import work_out, work_out_new
from apps.contacts.epochs import epoch_for, split
from apps.contacts.models import ContactEvent, PhoneEpoch
from apps.imports.models import CrmCreation
from apps.optouts.models import OptOutEvent
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.tenancy.scope import _scope

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 10, 6, 16, 0, tzinfo=UTC)  # a Tuesday
FAR = T0 + timedelta(days=1000)
n = iter(range(10**6))


@pytest.fixture(autouse=True)
def rulebook():
    return load(RULEBOOK_DIR / 'v3.0.yaml')[0]


def contact(client, at=T0, person='p1', channel='call', dial_mode='manual', lead_id='', direction='outbound'):
    c = ContactEvent.objects.create(client=client, phone_token=person, phone_token_kid='k1', source_system='convoso',
                                    source_record_id=f'r{next(n)}', source_grade='C', channel=channel, direction=direction,
                                    occurred_at=at, dial_mode=dial_mode, recipient_state='CA', time_zones=['America/Los_Angeles'],
                                    lead_id=lead_id, epoch=epoch_for(client.pk, person, at))
    return c


def cert(client, created=T0 - timedelta(days=2), state='claimed', expires=FAR, person='p1', lead_id='', error='', record='leads:1'):
    claim = CertificateClaim.objects.create(client=client, provider='trustedform', cert_ref=f'{next(n):040d}', state=state,
                                            deadline_at=created + timedelta(hours=72), cert_created_at=created if state == 'claimed' else None,
                                            cert_expires_at=expires if state == 'claimed' else None, last_error=error)
    return ConsentProof.objects.create(client=client, phone_token=person, epoch=epoch_for(client.pk, person, created), kind='certificate',
                                       proof_type='web_cert', certificate=claim, captured_at=created, date_known=state == 'claimed',
                                       source_system='salesforce', source_record_id=record, lead_id=lead_id)


def other(client, kind, proof_type, at=T0 - timedelta(days=30), person='p1'):
    return ConsentProof.objects.create(client=client, phone_token=person, epoch=epoch_for(client.pk, person, at), kind=kind,
                                       proof_type=proof_type, captured_at=at, source_system='hubspot', source_record_id=f'contacts:{next(n)}')


def result(c, variant='strict'):
    work_out(c)
    check_contact(c, as_of=T0)
    return ConsentResult.objects.get(contact=c, variant=variant)


def test_a_trustedform_lead_called_afterwards_is_verified(company):
    cert(company)
    r = result(contact(company, dial_mode='predictive'))
    assert (r.status, r.primary_code) == ('verified', 'VF_OK') and r.proof.kind == 'certificate'
    assert 'not_measured:consent_wording' in r.labels and 'not_measured:phone_match' in r.labels


def test_only_a_crm_box_is_no_proof_self_asserted(company):
    other(company, 'self_asserted', 'crm_flag')
    r = result(contact(company))
    assert (r.status, r.primary_code) == ('no_proof', 'NP_SELF_ASSERTED')


def test_nothing_at_all_is_no_proof(company):
    r = result(contact(company))
    assert (r.status, r.primary_code) == ('no_proof', 'NP_NONE')


def test_a_call_before_the_consent_is_no_proof(company):
    cert(company, created=T0 + timedelta(hours=1))
    assert result(contact(company)).primary_code == 'NP_BEFORE_CONSENT'


def test_after_stop_is_no_proof_but_one_confirmation_text_is_fine(company):
    cert(company)
    OptOutEvent.objects.create(client=company, phone_token='p1', at=T0, channel='text', method='keyword', source_system='twilio', source_record_id='SM1')
    confirmation = contact(company, at=T0 + timedelta(minutes=1), channel='text')
    later = contact(company, at=T0 + timedelta(days=2))
    assert result(confirmation).status == 'verified'
    assert result(later).primary_code == 'NP_AFTER_OPT_OUT'
    assert result(later, 'lenient').status == 'verified'  # lenient: 10 business days of grace


def test_a_new_consent_after_the_stop_restores_coverage_a_purchase_does_not(company):
    OptOutEvent.objects.create(client=company, phone_token='p1', at=T0, channel='text', method='keyword', source_system='twilio', source_record_id='SM1')
    other(company, 'ebr_purchase', 'purchase', at=T0 + timedelta(hours=1))
    assert result(contact(company, at=T0 + timedelta(days=2))).status == 'no_proof'
    cert(company, created=T0 + timedelta(hours=2))
    assert result(contact(company, at=T0 + timedelta(days=3))).status == 'verified'


def test_a_lost_certificate_is_conflicting(company):
    cert(company, state='lost')
    assert (result(contact(company)).status, result(contact(company)).primary_code) == ('conflicting', 'CF_EXPIRED')


def test_a_certificate_the_provider_does_not_have_is_conflicting_not_found(company):
    cert(company, state='lost', error='NotFound')
    assert result(contact(company)).primary_code == 'CF_NOT_FOUND'


def test_a_certificate_made_after_the_lead_was_delivered_is_conflicting(company):
    CrmCreation.objects.create(client=company, source_system='salesforce', record_id='leads:1', created_at=T0 - timedelta(days=3))
    cert(company, created=T0 - timedelta(days=2))
    assert result(contact(company)).primary_code == 'CF_CERT_AFTER_DELIVERY'


def test_unlinked_proof_one_minute_before_is_weak_linked_is_verified(company):
    cert(company, created=T0 - timedelta(minutes=1))
    assert result(contact(company)).primary_code == 'WK_TIMING_UNCERTAIN'
    cert(company, created=T0 - timedelta(seconds=45), person='p2', lead_id='L7')
    assert result(contact(company, person='p2', lead_id='L7')).status == 'verified'  # same lead: the chain proves the order


def test_a_certificate_expiring_soon_is_weak(company):
    cert(company, expires=T0 + timedelta(days=10))
    assert result(contact(company)).primary_code == 'WK_RETENTION'


def test_a_certificate_not_read_yet_is_pending(company):
    cert(company, state='waiting')
    assert (result(contact(company)).status, result(contact(company)).primary_code) == ('pending', 'PD_NOT_READ_YET')


def test_two_proofs_the_best_wins(company):
    cert(company, state='lost')
    cert(company)
    assert result(contact(company)).status == 'verified'


def test_existing_customer_is_labelled_and_never_covers_a_robocall(company):
    other(company, 'ebr_purchase', 'purchase')
    manual = result(contact(company, dial_mode='manual'))
    assert manual.status == 'verified' and 'EBR_ONLY' in manual.labels
    robo = result(contact(company, dial_mode='predictive'))
    assert robo.status == 'no_proof' and robo.primary_code == 'NP_WRONG_TYPE'


def test_two_needs_the_worst_wins(company, rulebook):
    from apps.rulebook.models import RuleValue
    RuleValue.objects.filter(version=rulebook, key='state_consent_rule').update(
        status='proposed', value=[{'channels': ['call'], 'consent_type_required': ['signed_form']}])
    rulebook.revision += 1
    rulebook.save()
    cert(company)
    r = result(contact(company, dial_mode='predictive'))
    assert {b['basis']: b['status'] for b in r.bases} == {'robocall_marketing': 'verified', 'dnc_unknown': 'verified', 'state_law': 'no_proof'}
    assert (r.status, r.primary_code) == ('no_proof', 'NP_WRONG_TYPE')


def test_owner_1s_proof_is_no_proof_for_owner_2(company):
    cert(company)
    split(company.pk, 'p1', T0 - timedelta(days=1), PhoneEpoch.Reason.CRM_MOVED)
    assert result(contact(company)).primary_code == 'NP_NONE'


def test_inbound_needs_nothing(company):
    assert result(contact(company, direction='inbound')).status == 'not_needed'


def test_new_contacts_get_results_within_a_minute_and_are_locked(company, other_company):
    for client in (company, other_company):
        contact(client)
    assert work_out_new() == 2
    assert ConsentResult.objects.count() == 4  # strict and lenient for each
    with _scope('client', str(company.pk)):
        assert set(ConsentResult.objects.values_list('client_id', flat=True)) == {company.pk}
