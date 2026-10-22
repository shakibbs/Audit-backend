"""Bug fix 2026-10-23: staff downloads of client reports and documents went to a "not found" page (files are private)."""
import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.access_log.models import AccessEntry
from apps.documents.models import ClientDocument
from apps.reports.models import Report
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    return client


def test_a_report_downloads_through_civ_and_is_logged(staff, company):
    from datetime import date
    report = Report.objects.create(client=company, name='Period audit report', period=date(2026, 9, 1), status='ready')
    report.file.save('x.pdf', ContentFile(b'%PDF-1.4 test'))
    page = staff.get(f'/civ-admin/reports/report/{report.pk}/change/').content.decode()
    assert '/client-reports/' not in page and f'/civ-admin/reports/report/{report.pk}/download/' in page
    got = staff.get(f'/civ-admin/reports/report/{report.pk}/download/')
    assert got.status_code == 200 and b''.join(got.streaming_content).startswith(b'%PDF')
    assert AccessEntry.objects.filter(action='report_downloaded', client_id=company.pk, actor_kind='staff').exists()


def test_a_document_has_no_dead_link(staff, company):
    ClientDocument.objects.create(client=company, kind='service_agreement', title='Agreement',
                                  file=SimpleUploadedFile('a.pdf', b'%PDF-1.4'), original_name='a.pdf', sha256='a' * 64)
    page = staff.get(f'/civ-admin/clients/client/{company.pk}/change/').content.decode()
    assert '/client-docs/' not in page and '/documents/' in page and '/open/' in page
