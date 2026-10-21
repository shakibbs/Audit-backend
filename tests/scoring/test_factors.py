"""Module 10 step 3: factors F1–F6 (100 − mean metric score, M10 / M34 twice), the stop rule (F2 / F3 at least 75),
pending factors left out with their weight spread (D partial), and the extra monthly metrics."""
from datetime import UTC, date, datetime

import pytest

from apps.contacts.models import ContactEvent
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.scoring.factors import factors
from apps.scoring.snapshots import snapshot
from apps.uploads.models import InternalListEntry, Source, UploadedFile

pytestmark = pytest.mark.django_db


def m(code, score, value=0, **more):
    return {'code': code, 'score': score, 'value': value, **more}


def by_key(result):
    return {f['key']: f for f in result['factors']}


def test_factor_is_100_minus_the_mean_and_m10_counts_twice():
    f = by_key(factors([m('M08', 100), m('M09', 50), m('M10', 50, value=0)]))['F3']
    assert f['value'] == 37.5 and f['metrics'] == ['M08', 'M09', 'M10']


def test_a_contact_after_a_stop_holds_f3_at_75():
    f = by_key(factors([m('M08', 100), m('M09', 100), m('M10', 100, value=1)]))['F3']
    assert f['value'] == 75.0 and f['heldBy'] == 'M10'


def test_worse_than_75_is_kept():
    assert by_key(factors([m('M10', 0, value=40)]))['F3']['value'] == 100.0


def test_internal_list_worst_case_holds_f2():
    f = by_key(factors([m('M12', 0, value=None, worstCase=True)]))['F2']
    assert f['value'] == 100.0


def test_pending_factors_are_left_out_and_d_is_partial():
    result = factors([m('M01', 80), m('M16', 100)])  # F1 = 20, F4 = 0; others pending
    assert by_key(result)['F5']['pending'] and result['partial']
    assert result['defect'] == round((20 * 0.28 + 0 * 0.16) / (0.28 + 0.16), 1)  # 12.7


def test_nothing_scored_means_no_d():
    assert factors([m('M38', None)])['defect'] is None


def test_display_only_metrics_never_move_a_factor():
    assert all(f['pending'] for f in factors([m('M38', 0, value=5), m('M41', 0, value=5), m('M45', 0, value=1)])['factors'])


def test_saved_month_has_factors_and_the_extra_metrics(company):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    upload = UploadedFile.objects.create(client=company, source=Source.INTERNAL_LIST, original_name='dnc.csv', sha256='a' * 64,
                                         received_at=datetime(2026, 8, 1, tzinfo=UTC))
    InternalListEntry.objects.create(client=company, upload=upload, phone_token='listed', added_on=date(2026, 8, 1))
    ContactEvent.objects.create(client=company, phone_token='listed', phone_token_kid='k1', source_system='vicidial', source_record_id='c1',
                                source_grade='B', channel='call', direction='outbound', occurred_at=datetime(2026, 9, 3, 16, tzinfo=UTC),
                                time_zones=['America/New_York'])
    run = snapshot(company, date(2026, 9, 1), now=datetime(2026, 9, 20, tzinfo=UTC))
    codes = {m.code: m for m in run.metrics.all()}
    assert codes['M12'].value == 1 and codes['M11'].state == 'worst_case' and codes['M45'].state == 'not_measured'
    f = by_key(run.score)
    assert f['F2']['value'] == 100.0 and 'heldBy' not in f['F2']  # already worse than 75: nothing to hold
    assert f['F6']['value'] == 100.0  # M11 worst case: reassigned logs not supplied
    assert run.score['partial'] and run.score['defect'] is not None
