"""Rulebook loader: the real v3.0 file loads; files the spec forbids are refused."""
import copy

import pytest
import yaml

from apps.rulebook.loader import RULEBOOK_DIR, RulebookRefused, check, load
from apps.rulebook.models import RulebookVersion, RuleValue

V3 = RULEBOOK_DIR / 'v3.0.yaml'


def doc():
    return yaml.safe_load(V3.read_text())


def rule(d, key):
    return next(r for r in d['rules'] if r['key'] == key)


@pytest.mark.django_db
def test_spec_v3_loads_as_provisional_with_state_rows():
    version, result = load(V3)
    assert result == 'loaded' and version.status == 'provisional' and version.version == '3.0'
    assert RuleValue.objects.filter(version=version, jurisdiction='US').count() == 149
    fl = RuleValue.objects.get(key='calling_hours', jurisdiction='FL')
    assert fl.status == 'tbd' and fl.provisional == {'start': '08:00', 'end': '20:00'} and fl.counsel_item == 'A6'
    deadline = RuleValue.objects.get(key='optout_deadline_business_days', jurisdiction='US')
    assert (deadline.value, deadline.status, deadline.owner, deadline.affects_status) == (10, 'proposed', 'Counsel', True)
    assert RuleValue.objects.get(key='optout_keywords').value[0] == 'STOP'


@pytest.mark.django_db
def test_unchanged_file_is_skipped_changed_provisional_reloads(tmp_path):
    load(V3)
    assert load(V3)[1] == 'unchanged'
    d = doc()
    rule(d, 'metric_window_days')['value'] = 45
    changed = tmp_path / 'v3.0.yaml'
    changed.write_text(yaml.safe_dump(d))
    assert load(changed)[1] == 'reloaded'
    assert RuleValue.objects.get(key='metric_window_days').value == 45
    assert RulebookVersion.objects.count() == 1


@pytest.mark.django_db
def test_an_approved_version_never_changes(tmp_path):
    d = doc()
    d['version'] = '9.0'
    RulebookVersion.objects.create(version='9.0', status='approved', effective_from='2027-01-01', source='x', file_sha256='0' * 64)
    path = tmp_path / 'v9.yaml'
    path.write_text(yaml.safe_dump(d))
    with pytest.raises(RulebookRefused, match='approved and cannot change'):
        load(path)


@pytest.mark.parametrize('break_it, message', [
    (lambda d: d['rules'].pop(0), 'missing keys: count_unanswered_calls'),
    (lambda d: d['rules'].append({**rule(d, 'lookback_years'), 'key': 'lookback_yeers'}), 'unknown keys'),
    (lambda d: d['rules'].append(copy.deepcopy(rule(d, 'lookback_years'))), 'keys listed twice'),
    (lambda d: rule(d, 'vs_rate_weights').update(value=[0.5, 0.6]), 'vs_rate_weights add up to'),
    (lambda d: rule(d, 'dedupe_window_seconds').update(value=60), 'dedupe_window_seconds is below clock_skew_seconds'),
    (lambda d: rule(d, 'lookback_years').update(value=None), 'lookback_years: proposed but has no value'),
    (lambda d: d.update(status='approved'), 'may not contain TBD keys'),
])
def test_files_the_spec_forbids_are_refused(break_it, message):
    d = doc()
    break_it(d)
    with pytest.raises(RulebookRefused, match=message):
        check(d)


def test_approved_needs_counsel_approval_of_result_changing_keys():
    d = doc()
    d['status'] = 'approved'
    for r in d['rules']:  # pretend counsel settled every TBD …
        if r['status'] == 'tbd':
            r.update(status='set', value=r.get('provisional') or 1)
        for place in r.get('jurisdictions', []):
            place['status'] = 'set'
        r['counsel_approved'] = True
    rule(d, 'li_signal_points')['counsel_approved'] = False  # … but not this Product key that changes lead results
    with pytest.raises(RulebookRefused, match='need counsel approval: li_signal_points$'):
        check(d)


# Same list as the portal's wording guard (frontend/src/lib/wording.ts).
BANNED = ['violation', 'violations', 'breach', 'breaches', 'illegal', 'compromised', 'fake', 'fraud', 'fraudulent', 'genuine',
          'compliant', 'non-compliant', 'noncompliant', 'ensures compliance', 'protects you', 'guaranteed', 'guarantee', 'scrub', 'screen']


def test_meaning_and_shown_text_have_no_banned_words():
    import re
    for r in doc()['rules']:
        text = f"{r['meaning']} {r['shown']}".lower()
        assert [w for w in BANNED if re.search(rf'(^|[^a-z]){w}(?=$|[^a-z])', text)] == [], r['key']


def test_spec_v3_still_needs_counsel_for_six_result_changing_keys():
    """Found while loading the spec: these change results but are neither counsel-owned nor marked counsel-approved."""
    d = doc()
    pending = sorted(r['key'] for r in d['rules'] if r['affects_status'] and r['owner'] != 'Counsel' and not r['counsel_approved'])
    assert pending == ['cert_confirmed_expiry_hours', 'cert_unretained_expiry_hours', 'conv_review_accuracy_pass_mark',
                       'conv_review_min_confidence', 'conv_review_stop_catch_mark', 'conv_review_thread_days']
