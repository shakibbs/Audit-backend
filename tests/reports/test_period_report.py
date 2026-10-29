"""Module 11 step 5: the monthly audit report — a PDF from the saved figures, decisions without notes, a figures
fingerprint in the footer, blocked on a banned word, made on the 6th or on request, kept 4 years."""
from datetime import UTC, date, datetime, timedelta

import pytest

from apps.access_log.models import AccessEntry
from apps.findings.models import Finding
from apps.reports.make import make_period, purge_old
from apps.reports.models import Report
from apps.reports.period import figures, text_of
from apps.reports.words import banned_words
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.scoring.models import MetricSnapshot, SnapshotRun

pytestmark = pytest.mark.django_db
SEP = date(2026, 9, 1)
NOW = datetime(2026, 9, 20, tzinfo=UTC)


@pytest.fixture(autouse=True)
def setup(company, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    load(RULEBOOK_DIR / 'v3.0.yaml')
    run = SnapshotRun.objects.create(client=company, period=SEP, ran_at=NOW, fingerprint='x',
                                     score={'factors': [{'key': 'F4', 'name': 'Calling conduct', 'value': 25.0, 'pending': False}],
                                            'defect': 25.0, 'exposure': {'value': 22.5, 'grade': 'A', 'venue': {'value': 1.0},
                                                                         'targeting': {'value': 1.0}, 'volume': {'value': 0.9},
                                                                         'caps': {'hard': {'state': 'rule_pending'}}}})
    MetricSnapshot.objects.create(client=company, run=run, code='M16', state='measured', value=3, score=50.0, display='3')
    MetricSnapshot.objects.create(client=company, run=run, code='M18', state='rule_pending', value=None, score=None, display='')
    Finding.objects.create(client=company, key='M16', metric='M16', domain='CTF', severity='Medium', title='Out-of-hours contacts',
                           why='CiV found 3 contacts in September 2026.', period=SEP, first_seen=NOW, last_seen=NOW,
                           decision='accepted', decision_note='Secret plan with counsel.')


def test_figures_show_decisions_but_never_the_note(company):
    data = figures(company, SEP)
    assert data['score'] == 50.0 and data['findings'][0]['decision'] == 'Accepted' and data['notMeasured'] == ['M18']
    assert 'Secret plan' not in text_of(data)


def test_report_is_a_pdf_with_its_fingerprints_and_is_logged(company):
    report = make_period(company, SEP, 'Dana Reyes')
    pdf = report.file.read()
    assert report.status == 'ready' and pdf.startswith(b'%PDF') and len(report.sha256) == 64 and len(report.content_sha256) == 64
    assert AccessEntry.objects.filter(action='report_made').exists()


def test_a_banned_word_blocks_the_report(company):
    assert banned_words('CiV found 3 violations; screenshot kept') == ['violations']
    Finding.objects.update(why='This is a violation.')
    report = make_period(company, SEP, 'Dana Reyes')
    assert report.status == 'blocked' and report.banned == ['violation'] and not report.file
    assert AccessEntry.objects.filter(action='report_blocked').exists()


def test_portal_generate_download_and_history(company, admin_user, signed_in):
    api = signed_in(admin_user)
    made = api.call('post', '/api/reports', {'name': 'Period audit report', 'period': 'Sep 2026'}).json()
    assert made['status'] == 'ready' and made['period'] == 'Sep 2026'
    file = api.get(made['url'])
    assert file.status_code == 200 and file['Content-Type'] == 'application/pdf'
    assert api.get('/api/reports/period?period=2026-09').status_code == 200  # the month's latest, not made again
    assert Report.objects.filter(status='ready').count() == 1
    assert api.call('post', '/api/reports', {'name': 'Certification pack', 'period': 'Sep 2026'}).status_code == 400  # from the bulk export
    assert [r['name'] for r in api.get('/api/reports').json()['runs']] == ['Period audit report']


def test_monthly_task_and_four_years(company):
    from apps.reports.tasks import monthly_reports
    from unittest import mock
    with mock.patch('apps.reports.tasks.timezone.localdate', return_value=date(2026, 10, 6)):
        assert monthly_reports() >= 1
    report = Report.objects.get(period=SEP)
    Report.objects.filter(pk=report.pk).update(made_at=NOW - timedelta(days=4 * 365 + 1))
    assert purge_old(NOW) == 1
    report.refresh_from_db()
    assert report.purged_at and not report.file and report.sha256


def test_the_rulebook_snapshot_is_kept_and_downloadable(company, admin_user, signed_in):
    api = signed_in(admin_user)
    made = api.call('post', '/api/reports', {'name': 'Rulebook snapshot', 'period': 'Sep 2026'}).json()
    assert made['status'] == 'ready' and made['url']
    file = api.get(made['url'])
    assert file.status_code == 200 and 'rulebook-snapshot-2026-09.pdf' in file['Content-Disposition']


def test_metric_export_is_a_csv_of_the_saved_month(company, admin_user, signed_in):
    api = signed_in(admin_user)
    made = api.call('post', '/api/reports', {'name': 'Metric export', 'period': 'Sep 2026'}).json()
    assert made['status'] == 'ready'
    file = api.get(made['url'])
    text = b''.join(file.streaming_content).decode()
    assert file['Content-Type'] == 'text/csv' and 'metrics-2026-09.csv' in file['Content-Disposition']
    assert text.splitlines()[0] == 'metric,value,shown,state,score_0_100,note'
    assert 'M16,3.0,3,Measured,50.0,' in text and 'M18,,,Rule pending,,' in text
