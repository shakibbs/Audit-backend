"""What proof a call or text needs, from the rules in force on its date."""
from datetime import UTC, date, datetime, timedelta

import pytest

from apps.consent.models import ConsentNeed, ConsentProof
from apps.consent.needs import meets, profile, work_out, work_out_new
from apps.contacts.models import ContactEvent
from apps.optouts.models import OptOutEvent
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.rulebook.lookup import RuleSet
from apps.rulebook.models import RuleValue
from apps.tenancy.scope import _scope

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)
WRITTEN = ['web_cert', 'signed_form', 'ivr_keypress_with_disclosures']


@pytest.fixture(autouse=True)
def rulebook():
    return load(RULEBOOK_DIR / 'v3.0.yaml')[0]


n = iter(range(10**6))


def contact(client, channel='call', dial_mode='', at=T0, person='p1', **extra):
    return ContactEvent.objects.create(client=client, phone_token=person, phone_token_kid='k1', source_system='convoso',
                                       source_record_id=f'r{next(n)}', source_grade='B', channel=channel, direction='outbound',
                                       occurred_at=at, dial_mode=dial_mode, recipient_state='CA', **extra)


def bases(c, variant='strict'):
    return {b['basis']: b['needs'] for b in profile(c, RuleSet(), variant)['bases']}


def test_an_autodialed_sales_call_needs_written_consent(company):
    found = profile(contact(company, dial_mode='predictive'), RuleSet(), 'strict')
    assert found['robocall'] and found['category'] == 'marketing' and found['is_legal_basis']
    assert bases(contact(company, dial_mode='predictive'))['robocall_marketing'] == WRITTEN


def test_an_unknown_dial_mode_is_treated_as_autodialed(company):
    found = profile(contact(company), RuleSet(), 'strict')
    assert found['robocall'] and 'dial_mode_unknown' in found['labels'] and 'category_unknown' in found['labels']
    lenient = profile(contact(company), RuleSet(), 'lenient')  # lenient: only prerecorded or AI voice counts
    assert not lenient['robocall'] and 'robocall_marketing' not in bases(contact(company), 'lenient')


def test_a_manual_call_is_not_a_robocall_and_a_marketing_text_is(company):
    assert not profile(contact(company, dial_mode='manual'), RuleSet(), 'strict')['robocall']
    assert profile(contact(company, channel='text'), RuleSet(), 'strict')['robocall']
    assert not profile(contact(company, channel='text'), RuleSet(), 'lenient')['robocall']


def test_a_number_on_the_stop_list_needs_a_signed_agreement_or_a_current_customer(company):
    OptOutEvent.objects.create(client=company, phone_token='p1', at=T0 - timedelta(days=3), channel='text', method='keyword',
                               source_system='twilio', source_record_id='SM1')
    found = bases(contact(company, dial_mode='manual'))
    assert found['dnc_listed'] == ['web_cert_with_esignature', 'signed_form', 'ebr_active'] and 'dnc_unknown' not in found


def test_no_do_not_call_list_is_labelled_not_a_mark_against_the_client(company):
    found = profile(contact(company, dial_mode='manual'), RuleSet(), 'strict')
    assert [b['basis'] for b in found['bases']] == ['dnc_unknown'] and 'dnc_list_not_supplied' in found['labels']
    assert not found['is_legal_basis']


def ebr(company, months_ago):
    return ConsentProof.objects.create(client=company, phone_token='p1', kind='ebr_purchase', proof_type='purchase',
                                       captured_at=T0 - timedelta(days=30 * months_ago), source_system='hubspot', source_record_id=f'contacts:{months_ago}')


def test_a_customer_older_than_18_months_does_not_count(company):
    call = contact(company, dial_mode='manual')
    need = profile(call, RuleSet(), 'strict')['bases'][0]
    assert meets(ebr(company, 12), need, call, False, RuleSet(), 'strict')
    assert not meets(ebr(company, 19), need, call, False, RuleSet(), 'strict')


def test_a_text_or_robocall_is_never_covered_by_an_existing_customer(company):
    proof = ebr(company, 2)
    text = contact(company, channel='text')
    for variant in ('strict', 'lenient'):
        found = profile(text, RuleSet(), variant)
        assert not any(meets(proof, b, text, found['robocall'], RuleSet(), variant) for b in found['bases'])
    robo = contact(company, dial_mode='predictive')
    assert not any(meets(proof, b, robo, True, RuleSet(), 'strict') for b in profile(robo, RuleSet(), 'strict')['bases'])


def test_a_crm_box_never_meets_any_need(company):
    call = contact(company, dial_mode='manual')
    box = ConsentProof(client=company, phone_token='p1', kind='self_asserted', proof_type='crm_flag')
    assert not meets(box, {'basis': 'dnc_unknown', 'needs': ['any']}, call, False, RuleSet(), 'strict')


def test_a_rule_change_only_applies_to_calls_after_its_date(company, rulebook):
    row = RuleValue.objects.get(version=rulebook, key='written_consent_types', jurisdiction='US')
    RuleValue.objects.filter(pk=row.pk).update(effective_to=date(2026, 10, 31))
    RuleValue.objects.create(**{f.name: getattr(row, f.name) for f in RuleValue._meta.fields if f.name not in ('id', 'effective_from', 'effective_to', 'value')},
                             effective_from=date(2026, 11, 1), value=['signed_form'])
    rulebook.revision += 1
    rulebook.save()
    assert bases(contact(company, dial_mode='predictive'))['robocall_marketing'] == WRITTEN
    assert bases(contact(company, dial_mode='predictive', at=T0 + timedelta(days=40)))['robocall_marketing'] == ['signed_form']


def test_inbound_and_test_calls_need_nothing(company):
    inbound = contact(company)
    inbound.direction = 'inbound'
    assert profile(inbound, RuleSet(), 'strict')['bases'] == []
    assert profile(contact(company, is_test=True), RuleSet(), 'strict')['bases'] == []


def test_both_variants_are_saved_once_and_locked_per_client(company, other_company):
    for client in (company, other_company):
        contact(client, person='p9')
    assert work_out_new() == 2 and work_out_new() == 0
    assert ConsentNeed.objects.count() == 4
    first = ConsentNeed.objects.filter(client=company).first()
    work_out(first.contact)
    assert ConsentNeed.objects.count() == 4 and first.rulebook_version == '3.0'
    with _scope('client', str(company.pk)):
        assert set(ConsentNeed.objects.values_list('client_id', flat=True)) == {company.pk}
