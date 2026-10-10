"""Documents tab: signed paperwork kept privately, fingerprinted, opened only by CiV staff."""
import hashlib
import os

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.access_log.models import AccessEntry
from apps.documents.models import ClientDocument
from apps.onboarding.progress import checklist
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

PDF = b'%PDF-1.4 signed agreement'


@pytest.fixture(autouse=True)
def private_media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def staff_client(client):
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    return client


def save_page(staff_client, company, row, existing=None):
    data = {'name': company.name, 'industry': 'Solar', 'plan': 'growth', 'start_date': '2026-10-01',
            'status': company.status, 'counsel_directed': 'on'}
    for prefix in ('connections', 'users', 'invites', 'contract'):
        data.update({f'{prefix}-TOTAL_FORMS': 0, f'{prefix}-INITIAL_FORMS': 0, f'{prefix}-MIN_NUM_FORMS': 0, f'{prefix}-MAX_NUM_FORMS': 1000})
    data.update({'documents-TOTAL_FORMS': 1, 'documents-INITIAL_FORMS': 1 if existing else 0,
                 'documents-MIN_NUM_FORMS': 0, 'documents-MAX_NUM_FORMS': 1000})
    if existing:
        row = {'id': existing.pk, 'client': company.pk, **row}
    data.update({f'documents-0-{k}': v for k, v in row.items()})
    return staff_client.post(f'/civ-admin/clients/client/{company.pk}/change/', data)


@pytest.mark.django_db
def test_upload_is_fingerprinted_and_logged(staff_client, company):
    upload = SimpleUploadedFile('MSA signed.pdf', PDF, content_type='application/pdf')
    response = save_page(staff_client, company, {'kind': 'agreement', 'title': 'MSA', 'file': upload, 'signed_on': '2026-10-01'})
    assert response.status_code == 302, response.content.decode()[:1500]
    document = ClientDocument.objects.get()
    assert document.sha256 == hashlib.sha256(PDF).hexdigest() and document.size == len(PDF)
    assert document.original_name == 'MSA signed.pdf' and document.uploaded_by.name == 'Team'
    assert 'MSA signed' not in document.file.name  # stored under a random name
    assert AccessEntry.objects.filter(action='document_added', client_id=company.pk).exists()


@pytest.mark.django_db
def test_a_link_alone_is_enough_but_nothing_is_not(staff_client, company):
    assert save_page(staff_client, company, {'kind': 'dpa', 'link': 'https://drive.example.com/dpa'}).status_code == 302
    assert save_page(staff_client, company, {'kind': 'other', 'title': 'empty'}).status_code == 200  # form error
    assert ClientDocument.objects.count() == 1


@pytest.mark.django_db
def test_unsafe_file_types_are_refused(staff_client, company):
    upload = SimpleUploadedFile('page.html', b'<script>alert(1)</script>', content_type='text/html')
    assert save_page(staff_client, company, {'kind': 'other', 'file': upload}).status_code == 200
    assert not ClientDocument.objects.exists()


@pytest.mark.django_db
def test_only_staff_can_open_and_opening_is_logged(staff_client, client, company):
    save_page(staff_client, company, {'kind': 'agreement', 'file': SimpleUploadedFile('a.pdf', PDF)})
    document = ClientDocument.objects.get()
    url = f'/civ-admin/clients/client/{company.pk}/documents/{document.pk}/open/'
    response = staff_client.get(url)
    assert response.status_code == 200 and b''.join(response.streaming_content) == PDF
    assert 'no-store' in response['Cache-Control'] and 'private' in response['Cache-Control']
    assert AccessEntry.objects.filter(action='document_opened').exists()
    staff_client.logout()
    assert client.get(url).status_code == 302  # not signed in: sent to the admin login
    assert client.get('/media/' + document.file.name).status_code == 404  # no public address for files


@pytest.mark.django_db
def test_removing_a_document_deletes_the_file(staff_client, company):
    save_page(staff_client, company, {'kind': 'agreement', 'file': SimpleUploadedFile('a.pdf', PDF)})
    document = ClientDocument.objects.get()
    path = document.file.path
    save_page(staff_client, company, {'kind': 'agreement', 'DELETE': 'on'}, existing=document)
    assert not ClientDocument.objects.exists()
    assert not os.path.exists(path)
    assert AccessEntry.objects.filter(action='document_removed').exists()


@pytest.mark.django_db
def test_uploading_agreement_and_annex_c_completes_those_onboarding_steps(staff_client, company):
    save_page(staff_client, company, {'kind': 'annex_c', 'file': SimpleUploadedFile('c.pdf', PDF)})
    steps = {s['code']: s for s in checklist(company)['steps']}
    assert steps['annex_c']['done'] and steps['annex_c']['by_document']
    assert not steps['agreement']['done']
