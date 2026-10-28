"""Owner, 2026-10-24: after an upload, the client's month is worked out again within minutes (not at 04:00), so a
"not supplied" finding resolves and the session says when scores were last worked out."""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.clients.models import Client
from apps.findings.models import Finding
from apps.scoring.tasks import refresh_one
from apps.tenancy.scope import all_clients

pytestmark = pytest.mark.django_db


def test_uploading_the_internal_list_resolves_its_finding_right_away(company, admin_user, signed_in, django_capture_on_commit_callbacks):
    refresh_one(company.pk)  # as after a night run: the list is missing
    with all_clients():
        assert Finding.objects.filter(client=company, key__startswith='M12', status='open').exists()
    api = signed_in(admin_user)
    token = api.cookies['csrftoken'].value
    with django_capture_on_commit_callbacks(execute=True):
        reply = api.post('/api/uploads', {'source': 'Internal do-not-contact list',
                                          'file': SimpleUploadedFile('dnc.csv', b'phone,added\n9165550142,2026-09-01\n')}, HTTP_X_CSRFTOKEN=token)
    assert reply.status_code == 200
    with all_clients():
        assert not Finding.objects.filter(client=company, key__startswith='M12', status='open').exists()
    session = api.get('/api/session').json()
    assert session['scoredAt'] and session['updating'] is False
    assert Client.objects.get(pk=company.pk).refresh_pending_since is None
