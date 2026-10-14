"""Rulebook lookup: right place, right date, and honest about Proposed and TBD values."""
from datetime import date

import pytest

from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.rulebook.lookup import NoRulebook, RulePending, RuleSet, UnknownRule, rule
from apps.rulebook.models import RulebookVersion, RuleValue

SEP_12 = date(2026, 9, 12)


@pytest.fixture
def rulebook(db):
    return load(RULEBOOK_DIR / 'v3.0.yaml')[0]


def test_a_state_rule_wins_over_federal(rulebook):
    fl = rule('calling_hours', on=SEP_12, state='fl', mode='draft')
    assert fl.jurisdiction == 'FL' and fl.value == {'start': '08:00', 'end': '20:00'}
    nv = rule('calling_hours', on=SEP_12, state='NV', mode='draft')  # no Nevada row: federal
    assert nv.jurisdiction == 'US' and nv.value == {'start': '08:00', 'end': '21:00'}
    assert rule('calling_hours', on=SEP_12, state='TX', mode='draft').value['sunday_start'] == '12:00'


def test_set_proposed_and_tbd(rulebook):
    skew = rule('clock_skew_seconds', on=SEP_12)
    assert (skew.value, skew.provisional, skew.pending) == (120, False, False)
    deadline = rule('optout_deadline_business_days', on=SEP_12)
    assert (deadline.value, deadline.provisional, deadline.counsel_item) == (10, True, 'A1')
    hours = rule('calling_hours', on=SEP_12, state='FL')  # TBD: never a guess in a real run
    assert hours.pending and hours.value is None and hours.shown == 'Not set yet'
    with pytest.raises(RulePending, match='RULE_PENDING'):
        hours.require()


def test_a_pending_state_rule_is_not_replaced_by_federal(rulebook):
    assert rule('calling_hours', on=SEP_12, state='CT').jurisdiction == 'CT'


def test_draft_runs_use_test_values_and_variants(rulebook):
    assert rule('optout_grace_business_days', on=SEP_12, mode='draft', variant='strict').value == 0
    assert rule('optout_grace_business_days', on=SEP_12, mode='draft', variant='lenient').value == 10
    assert rule('sms_treated_as_autodialed', on=SEP_12, mode='draft', variant='lenient').value is False
    assert rule('sms_treated_as_autodialed', on=SEP_12).value is True  # outside draft runs: the Proposed value
    assert rule('cc_min_font_px', on=SEP_12, mode='draft').value == 10


def test_court_forum_row(rulebook):
    assert rule('written_consent_required_by_forum', on=SEP_12, forum='5th_circuit').pending
    assert rule('written_consent_required_by_forum', on=SEP_12, forum='9th_circuit').value is True


def test_each_date_gets_the_value_in_force_then(rulebook):
    RuleValue.objects.filter(key='optout_deadline_business_days').update(effective_to=date(2026, 12, 31))
    newer = RuleValue.objects.get(key='optout_deadline_business_days')
    newer.pk, newer.value, newer.shown, newer.effective_from, newer.effective_to = None, 5, '5', date(2027, 1, 1), None
    newer.save()
    RulebookVersion.objects.filter(pk=rulebook.pk).update(file_sha256='changed')  # new rows: read again
    assert rule('optout_deadline_business_days', on=SEP_12).value == 10
    assert rule('optout_deadline_business_days', on=date(2027, 3, 1)).value == 5


def test_unknown_key_and_mode_rules(rulebook):
    with pytest.raises(UnknownRule):
        rule('calling_hourz', on=SEP_12)
    with pytest.raises(NoRulebook):  # v3.0 is provisional: nothing may reach a client yet
        rule('clock_skew_seconds', on=SEP_12, mode='client')


def test_one_ruleset_for_many_lookups(rulebook, django_assert_num_queries):
    rules = RuleSet()
    with django_assert_num_queries(0):
        for state in ['FL', 'OK', 'MD', 'CT', 'TX', 'NV', 'CA']:
            rules.get('calling_hours', on=SEP_12, state=state)
