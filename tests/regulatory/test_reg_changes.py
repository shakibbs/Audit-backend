"""Regulatory changes: the four starting changes, checks on rules, metrics and wording, and the admin pages."""
import pytest
from django.core.exceptions import ValidationError

from apps.access_log.models import AccessEntry
from apps.regulatory.models import RegChange
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD


@pytest.fixture
def rulebook(db):
    return load(RULEBOOK_DIR / 'v3.0.yaml')[0]


@pytest.fixture
def staff(client, db):
    user = StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD)
    client.force_login(user)
    return user


def change(**overrides):
    return RegChange(**{'title': 'Oregon limits texts', 'jurisdiction': 'Oregon', 'status': 'in_force', 'announced_on': '2026-01-01',
                        'effective_text': '1 Jan 2026', 'summary': 'Texts limited to 8am–8pm.', 'rule_keys': ['calling_hours'],
                        'metrics': ['M16'], 'source': 'Oregon HB 3865', **overrides})


@pytest.mark.django_db
def test_four_starting_changes_are_loaded_to_check():
    assert RegChange.objects.exclude(jurisdiction='CiV draft').count() == 4  # plus CiV's vendor clauses draft (Module 12)
    assert set(RegChange.objects.values_list('review', flat=True)) == {'to_check'}
    assert RegChange.objects.get(jurisdiction='Oregon').rule_keys == ['calling_hours', 'frequency_limits', 'quiet_hours_apply_to_sms']


def test_rules_must_exist_in_the_rulebook(rulebook):
    change().full_clean()
    with pytest.raises(ValidationError, match='Not in the Rulebook: calling_hourz'):
        change(rule_keys=['calling_hourz']).full_clean()


def test_metric_codes_and_wording_are_checked(rulebook):
    with pytest.raises(ValidationError, match='Not a metric code'):
        change(metrics=['16']).full_clean()
    with pytest.raises(ValidationError, match='violation'):
        change(summary='A text is now a violation.').full_clean()


def test_every_starting_change_passes_the_checks(rulebook):
    for c in RegChange.objects.all():
        c.full_clean()


def test_staff_add_a_change_in_the_admin_and_it_is_logged(client, staff, rulebook):
    page = client.post('/civ-admin/regulatory/regchange/add/', {
        'title': 'Florida shortens calling hours', 'jurisdiction': 'Florida', 'status': 'proposed', 'announced_on': '2026-10-01',
        'effective_text': 'Not yet in force', 'summary': 'A bill would end calls at 7pm.', 'rule_keys': ['calling_hours'],
        'metrics': 'M16', 'source': 'Florida HB 1', 'review': 'to_check',
        'rule_updates-TOTAL_FORMS': '0', 'rule_updates-INITIAL_FORMS': '0'})
    assert page.status_code == 302
    added = RegChange.objects.get(jurisdiction='Florida')
    assert added.rule_keys == ['calling_hours'] and added.metrics == ['M16'] and added.suggested_by == 'team@complyiv.com'
    assert AccessEntry.objects.filter(action='reg_change_added', object='Florida shortens calling hours').exists()


def test_rulebook_page_lists_rules_and_is_read_only(client, staff, rulebook):
    page = client.get('/civ-admin/rulebook/rulevalue/?q=calling_hours')
    text = page.content.decode()
    assert page.status_code == 200 and 'calling_hours' in text and 'Florida (FL)' in text  # places in plain names (owner, 2026-10-31)
    assert client.get('/civ-admin/rulebook/rulevalue/add/').status_code == 403
    rule = rulebook.rules.get(key='calling_hours', jurisdiction='FL')
    assert client.post(f'/civ-admin/rulebook/rulevalue/{rule.pk}/change/', {'shown': 'x'}).status_code == 403


def test_both_pages_are_in_the_menu(client, staff):
    text = client.get('/civ-admin/').content.decode()
    assert 'Rulebook' in text and 'Regulatory changes' in text


def test_domains_it_affects_are_kept_and_checked(rulebook):
    from django.core.exceptions import ValidationError

    from apps.regulatory.models import RegChange
    change = RegChange(title='T', jurisdiction='US', status='proposed', effective_text='soon', summary='s', source='x',
                       announced_on='2026-10-01', domains=['REV', 'SMS'])
    change.full_clean()
    change.domains = ['revocation']
    with pytest.raises(ValidationError, match='Not a domain code'):
        change.full_clean()
