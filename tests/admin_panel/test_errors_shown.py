"""QA 2026-10-23: a whole-row problem on a tab must show its reason, not only "Please correct the errors below"."""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def page(company, **extra):
    data = {'name': company.name, 'industry': 'Solar', 'plan': 'growth', 'start_date': '2026-10-01', 'status': company.status}
    for prefix in ('connections', 'users', 'invites', 'invites-2', 'contract', 'documents'):
        data.update({f'{prefix}-TOTAL_FORMS': 0, f'{prefix}-INITIAL_FORMS': 0, f'{prefix}-MIN_NUM_FORMS': 0, f'{prefix}-MAX_NUM_FORMS': 1000})
    data.update(extra)
    return data


@pytest.fixture
def staff(client):
    client.force_login(StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD))
    return client


def test_a_key_for_an_allow_tool_says_why(staff, company):
    data = page(company, **{'connections-TOTAL_FORMS': 1, 'connections-0-provider': 'hubspot', 'connections-0-key': 'pat-123'})
    reply = staff.post(f'/civ-admin/clients/client/{company.pk}/change/', data)
    assert reply.status_code == 200 and 'connects by the client clicking Allow' in reply.content.decode()


def test_a_document_without_a_file_or_link_says_why(staff, company):
    data = page(company, **{'documents-TOTAL_FORMS': 1, 'documents-0-kind': 'agreement', 'documents-0-title': 'Agreement'})
    reply = staff.post(f'/civ-admin/clients/client/{company.pk}/change/', data)
    text = reply.content.decode()
    assert reply.status_code == 200 and 'Add a file or a link' in text
