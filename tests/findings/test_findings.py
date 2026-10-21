"""Module 11 step 1: findings from the latest saved month — measured problems below 100 and worst cases, never "not
measured"; severity, masked examples, order; updated in place, closed when gone, reopened when back."""
from datetime import UTC, date, datetime

import pytest

from apps.consent.models import ConsentResult
from apps.contacts.models import ContactEvent
from apps.findings.build import ranked, refresh
from apps.findings.models import Finding
from apps.scoring.models import MetricSnapshot, SnapshotRun

pytestmark = pytest.mark.django_db
SEP = date(2026, 9, 1)
NOW = datetime(2026, 9, 20, tzinfo=UTC)
n = iter(range(10**6))


def run(company, metrics: list[tuple], period=SEP):
    r = SnapshotRun.objects.create(client=company, period=period, version=next(n) + 1, ran_at=NOW, fingerprint='x')
    for code, state, value, score in metrics:
        MetricSnapshot.objects.create(client=company, run=r, code=code, state=state, value=value, score=score, display=str(value))
    return r


def after_stop(company, label):
    c = ContactEvent.objects.create(client=company, phone_token=f'p{next(n)}', phone_token_kid='k1', source_system='twilio',
                                    source_record_id=f'm{next(n)}', source_grade='C', channel='text', direction='outbound',
                                    occurred_at=datetime(2026, 9, 3, 16, tzinfo=UTC), masked_label=label)
    ConsentResult.objects.create(client=company, contact=c, variant='strict', status='no_proof', codes=['NP_AFTER_OPT_OUT'],
                                 evaluation_as_of=c.occurred_at, rulebook_version='3.0')
    return c


def by_key(company):
    return {f.key: f for f in Finding.objects.filter(client=company)}


def test_problems_become_findings_and_perfect_or_unmeasured_do_not(company):
    after_stop(company, '(480) •••-0923')
    run(company, [('M10', 'measured', 1, 50.0), ('M16', 'measured', 0, 100.0), ('M18', 'not_measured', None, None),
                  ('M12', 'worst_case', None, 0.0), ('M38', 'measured', 2, 50.0)])
    assert refresh(company, NOW) == 2
    found = by_key(company)
    assert set(found) == {'M10', 'M12-worst'}
    m10 = found['M10']
    assert (m10.title, m10.severity, m10.domain, m10.affected, m10.numbers) == ('Contacts after an opt-out', 'High', 'REV', 1, 1)
    assert m10.why == 'CiV found 1 contact (1 number) in September 2026.'
    assert m10.examples[0]['label'] == '(480) •••-0923' and m10.examples[0]['ref'].startswith('p-')
    assert found['M12-worst'].title == 'Internal do-not-call list not supplied' and found['M12-worst'].severity == 'Medium'


def test_words_never_say_violation():
    from apps.findings.catalog import MEASURED, WORST
    text = ' '.join(t for t, *_ in MEASURED.values()) + ' '.join(t + w for t, _, w in WORST.values())
    assert not any(bad in text.lower() for bad in ('violation', 'illegal', 'breach', 'non-compliant', 'you must'))


def test_order_is_severity_then_how_many(company):
    run(company, [('M15', 'measured', 40, 0.0), ('M16', 'measured', 3, 50.0), ('M10', 'measured', 1, 50.0), ('M17', 'measured', 9, 0.0)])
    refresh(company, NOW)
    assert [f.metric for f in ranked(company)] == ['M10', 'M16', 'M15', 'M17']


def test_closes_when_gone_and_reopens_when_back(company):
    run(company, [('M16', 'measured', 3, 50.0)])
    refresh(company, NOW)
    first = Finding.objects.get()
    run(company, [('M16', 'measured', 0, 100.0)])
    assert refresh(company, NOW) == 0
    first.refresh_from_db()
    assert first.status == 'resolved' and first.resolved_at == NOW
    run(company, [('M16', 'measured', 5, 50.0)])
    refresh(company, NOW)
    first.refresh_from_db()
    assert (first.status, first.affected, Finding.objects.count()) == ('reopened', 5, 1)


def test_action_queue_api(company, admin_user, signed_in):
    after_stop(company, '(916) •••-5527')
    run(company, [('M10', 'measured', 1, 50.0), ('M11', 'worst_case', None, 0.0)])
    refresh(company, NOW)
    rows = signed_in(admin_user).get('/api/actions').json()
    assert [r['rank'] for r in rows] == [1, 2] and rows[0]['title'] == 'Contacts after an opt-out'
    assert rows[0]['impact'].startswith('+') and rows[0]['examples'][0]['label'] == '(916) •••-5527' and rows[0]['status'] == 'open'
    assert rows[1]['impact'].startswith('+') and rows[1]['domain'] == 'RND'


def test_nightly_task_updates_findings(company):
    from apps.scoring.tasks import snapshot_metrics
    snapshot_metrics()
    assert Finding.objects.filter(client=company, key='M12-worst').exists()  # no internal list uploaded
