"""Rule updates: nothing changes until approval; then exactly one value per rule, place and day."""
from datetime import date

import pytest
import yaml

from apps.access_log.models import AccessEntry
from apps.regulatory.approve import approve
from apps.regulatory.models import RegChange, RuleUpdate
from apps.rulebook.apply import OverlapRefused, check_no_overlap
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.rulebook.lookup import rule
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

OREGON_HOURS = {'start': '08:00', 'end': '20:00'}


@pytest.fixture
def rulebook(db):
    return load(RULEBOOK_DIR / 'v3.0.yaml')[0]


@pytest.fixture
def staff(client, db):
    user = StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD)
    client.force_login(user)
    return user


def oregon_update(**overrides):
    law = RegChange.objects.get(jurisdiction='Oregon')
    return RuleUpdate.objects.create(**{'reg_change': law, 'key': 'calling_hours', 'jurisdiction': 'OR', 'value': OREGON_HOURS,
                                        'shown': '8am – 8pm', 'status': 'set', 'effective_from': date(2026, 1, 1),
                                        'proposed_by': 'team@complyiv.com', **overrides})


def test_nothing_changes_until_approved(rulebook):
    oregon_update()
    assert rule('calling_hours', on=date(2026, 2, 3), state='OR').jurisdiction == 'US'


def test_approved_update_starts_on_its_date_and_old_dates_keep_the_old_value(rulebook, staff):
    approve(oregon_update(), staff)
    before, after = rule('calling_hours', on=date(2025, 12, 15), state='OR'), rule('calling_hours', on=date(2026, 2, 3), state='OR')
    assert before.jurisdiction == 'US'  # before Jan 1: no Oregon rule yet, so federal
    assert after.jurisdiction == 'OR' and after.value == OREGON_HOURS and after.status == 'set' and not after.pending
    assert AccessEntry.objects.filter(action='rule_update_approved').exists()


def test_a_second_update_closes_the_first(rulebook, staff):
    approve(oregon_update(), staff)
    approve(oregon_update(value={'start': '09:00', 'end': '20:00'}, shown='9am – 8pm', effective_from=date(2027, 1, 1)), staff)
    assert rule('calling_hours', on=date(2026, 6, 1), state='OR').value == OREGON_HOURS
    assert rule('calling_hours', on=date(2027, 6, 1), state='OR').value['start'] == '09:00'
    check_no_overlap(rulebook)  # one value per day


def test_an_overlapping_update_is_refused_and_nothing_is_saved(rulebook, staff):
    approve(oregon_update(effective_from=date(2027, 1, 1)), staff)
    earlier = oregon_update(effective_from=date(2026, 6, 1))
    with pytest.raises(OverlapRefused, match='pick a later start date'):
        approve(earlier, staff)
    earlier.refresh_from_db()
    assert earlier.state == 'waiting'
    assert rule('calling_hours', on=date(2026, 7, 1), state='OR').jurisdiction == 'US'


def test_approved_updates_survive_a_reload_of_the_file(rulebook, staff, tmp_path):
    approve(oregon_update(), staff)
    doc = yaml.safe_load((RULEBOOK_DIR / 'v3.0.yaml').read_text())
    next(r for r in doc['rules'] if r['key'] == 'metric_window_days')['value'] = 45
    changed = tmp_path / 'v3.0.yaml'
    changed.write_text(yaml.safe_dump(doc))
    assert load(changed)[1] == 'reloaded'
    assert rule('calling_hours', on=date(2026, 2, 3), state='OR').value == OREGON_HOURS
    assert rule('metric_window_days', on=date(2026, 2, 3)).value == 45


def test_the_spec_file_has_one_value_per_day(rulebook):
    check_no_overlap(rulebook)


def law_form(law, rows):
    base = {'title': law.title, 'jurisdiction': law.jurisdiction, 'status': law.status, 'announced_on': str(law.announced_on),
            'effective_text': law.effective_text, 'summary': law.summary, 'rule_keys': law.rule_keys,
            'metrics': ', '.join(law.metrics), 'source': law.source, 'review': 'to_check',
            'rule_updates-TOTAL_FORMS': str(len(rows)), 'rule_updates-INITIAL_FORMS': '0'}
    for i, row in enumerate(rows):
        base.update({f'rule_updates-{i}-{k}': v for k, v in row.items()})
    return base


ROW = {'key': 'calling_hours', 'new_key': '', 'new_meaning': '', 'jurisdiction': 'or', 'value': '{"start": "08:00", "end": "20:00"}',
       'shown': '8am – 8pm', 'status': 'set', 'effective_from': '2026-01-01'}


def test_add_on_the_law_change_stays_draft_then_approve_on_the_same_page(client, staff, rulebook):
    law = RegChange.objects.get(jurisdiction='Oregon')
    page = client.post(f'/civ-admin/regulatory/regchange/{law.pk}/change/', law_form(law, [ROW]))
    assert page.status_code == 302, page.content.decode()[:3000]
    update = RuleUpdate.objects.get()
    assert (update.jurisdiction, update.proposed_by, update.state) == ('OR', 'team@complyiv.com', 'waiting')
    assert update.get_state_display().startswith('Draft')
    assert rule('calling_hours', on=date(2026, 2, 3), state='OR').jurisdiction == 'US'  # draft: not used
    text = client.get(f'/civ-admin/regulatory/regchange/{law.pk}/change/').content.decode()
    assert 'Approve' in text and 'Reject' in text
    client.post(f'/civ-admin/regulatory/regchange/rule-update/{update.pk}/approve/')
    update.refresh_from_db()
    assert update.state == 'approved' and update.approved_by == 'team@complyiv.com'
    assert rule('calling_hours', on=date(2026, 2, 3), state='OR').value == OREGON_HOURS


def test_reject_keeps_it_on_record_and_unused(client, staff, rulebook):
    update = oregon_update()
    client.post(f'/civ-admin/regulatory/regchange/rule-update/{update.pk}/reject/')
    update.refresh_from_db()
    assert update.state == 'rejected'
    assert rule('calling_hours', on=date(2026, 2, 3), state='OR').jurisdiction == 'US'


def test_only_approvers_can_approve(client, rulebook):
    plain = StaffUser.objects.create_user(email='helper@complyiv.com', name='Helper', password=PASSWORD)
    client.force_login(plain)
    update = oregon_update()
    client.post(f'/civ-admin/regulatory/regchange/rule-update/{update.pk}/approve/')
    update.refresh_from_db()
    assert update.state == 'waiting'


def test_blank_modifies_rule_means_a_brand_new_rule(rulebook, staff):
    law = RegChange.objects.get(jurisdiction='Oregon')
    new = RuleUpdate(reg_change=law, key='', new_key='ai_voice_disclosure', new_meaning='AI voice calls must say they are AI',
                     jurisdiction='OR', value=True, shown='Required', status='set', effective_from=date(2026, 1, 1))
    new.full_clean()
    new.save()
    approve(new, staff)
    added = rule('ai_voice_disclosure', on=date(2026, 2, 3), state='OR')
    assert added.value is True and added.jurisdiction == 'OR'


@pytest.mark.parametrize('fields, message', [
    ({'key': '', 'new_key': '', 'new_meaning': ''}, 'Pick the rule it modifies, or name the new rule'),
    ({'key': '', 'new_key': 'calling_hours', 'new_meaning': 'x'}, 'This rule already exists'),
    ({'key': '', 'new_key': 'ai_voice_disclosure', 'new_meaning': ''}, 'what the new rule means|Say in one line'),
    ({'key': 'calling_hours', 'new_key': 'extra', 'new_meaning': ''}, 'Leave the new-rule fields blank'),
])
def test_modify_or_new_is_checked(rulebook, fields, message):
    from django.core.exceptions import ValidationError
    law = RegChange.objects.get(jurisdiction='Oregon')
    update = RuleUpdate(reg_change=law, jurisdiction='OR', value=1, shown='x', status='set', effective_from=date(2026, 1, 1), **fields)
    with pytest.raises(ValidationError, match=message):
        update.full_clean()
