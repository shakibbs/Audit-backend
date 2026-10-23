"""Super test 2026-10-23: odd input gets a short message, never a crash or Django's error page."""
import pytest
from django.test import Client as Browser

from apps.accounts.models import ClientUser
from apps.connections.models import Connection, Status
from apps.connections.testers import run_test
from apps.conversations.models import ExamCase
from apps.refs import day, month, number, yes
from apps.staff.models import StaffUser
from apps.uploads.models import UploadedFile
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_the_helpers_refuse_odd_values():
    assert (number('12'), number('²'), number('٣'), number('9' * 20)) == (12, None, None, None)
    assert (month('2026-09'), month('2026-13'), month('9999-12'), month('٢٠٢٦-٠١')) == ('2026-09', None, None, None)
    assert day('2026-09-04') and day('9999-12-31') is None and day('nope') is None
    assert (yes(True), yes('true'), yes('false'), yes('nope'), yes(1)) == (True, True, False, False, False)


def test_odd_ids_months_and_bodies_get_a_message(company, admin_user, signed_in):
    api = signed_in(admin_user)
    for path in ['/api/contacts/ce-²', '/api/reports/rep-²/file', '/api/insureds/c-²', '/api/metrics?period=2026-13',
                 '/api/score?period=9999-99', '/api/conduct?period=9999-12', '/api/rulebook/calendar?year=abc',
                 '/api/position?phone=9165550142&date=9999-12-31', '/api/users/u-2/extra', '/api/search?q=12%0034']:
        reply = api.get(path)
        assert reply.status_code < 500 and reply['Content-Type'].startswith('application/json'), path
    for body in [{'status': ['open']}, {'decision': 'x'}, {'due': 123}, {'dispute': {'note': ['x']}}]:
        assert api.call('patch', '/api/actions/f-1', body).status_code in (400, 404)
    assert api.call('post', '/api/can-call', ['x']).status_code == 400  # a list instead of an object
    assert api.call('post', '/api/statements', {'topic': 'other', 'text': 'a\u0000b'}).status_code == 400  # hidden character
    assert api.call('post', '/api/evidence-bundle', {'numbers': 'notalist'}).status_code == 400
    assert api.call('patch', '/api/setup/states', {'done': 'false'}).json()['done'] is False
    assert api.call('post', '/api/reports', {'name': 'Period audit report', 'period': '1800-01'}).status_code == 400


def test_a_refused_csrf_check_answers_in_json():
    reply = Browser(enforce_csrf_checks=True).post('/api/session/sign-in', {'email': 'x', 'password': 'y'}, content_type='application/json')
    assert reply.status_code == 403 and reply.json()['detail'].startswith('Your page is out of date')


def test_an_upload_that_cannot_be_read_is_not_kept_and_a_repeat_is_refused(company, admin_user, signed_in):
    from django.core.files.uploadedfile import SimpleUploadedFile
    api = signed_in(admin_user)
    token = api.cookies['csrftoken'].value
    big = api.post('/api/uploads', {'source': 'Complaint log', 'file': SimpleUploadedFile('big.csv', b'x' * 200_000)}, HTTP_X_CSRFTOKEN=token)
    good = SimpleUploadedFile('dnc.csv', b'phone,added\n9165550142,2026-09-01\n')
    first = api.post('/api/uploads', {'source': 'Internal do-not-contact list', 'file': good}, HTTP_X_CSRFTOKEN=token)
    good.seek(0)
    again = api.post('/api/uploads', {'source': 'Internal do-not-contact list', 'file': good}, HTTP_X_CSRFTOKEN=token)
    assert first.status_code == 200 and again.status_code == 400 and 'already uploaded' in again.json()['detail']
    assert big.status_code in (200, 400) and UploadedFile.objects.filter(client=company).count() == (2 if big.status_code == 200 else 1)


def test_emails_are_kept_in_small_letters_and_a_duplicate_in_capitals_is_refused(client, company, admin_user):
    boss = StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD)
    client.force_login(boss)
    same = client.post('/civ-admin/staff/staffuser/add/', {'email': 'BOSS@ComplyIV.com', 'name': 'Twin'})
    assert same.status_code == 200 and 'already exists' in same.content.decode() and StaffUser.objects.count() == 1
    user = ClientUser.objects.create_user(client=company, email='Kim@SunPath.com', name='Kim', password=PASSWORD)
    assert user.email == 'kim@sunpath.com'
    user.email = 'DANA@sunpath.com'  # admin_user's email in capitals
    with pytest.raises(Exception):
        user.full_clean()


def test_test_connection_never_crashes_and_fits_its_box(company, monkeypatch):
    from apps.connections import testers
    conn = Connection.objects.create(client=company, provider='twilio', status=Status.UNTESTED)
    conn.set_credentials({'account': 'AC1', 'key': 'k'})
    conn.save()
    monkeypatch.setitem(testers.TESTERS, 'twilio', lambda creds: (_ for _ in ()).throw(ValueError('bad JSON')))
    assert run_test(conn)[0] == Status.FAILED
    monkeypatch.setitem(testers.TESTERS, 'twilio', lambda creds: (Status.FAILED, 'x' * 1000))
    assert len(run_test(conn)[1]) <= 300


def test_an_exam_question_must_have_proper_turns():
    from django.core.exceptions import ValidationError
    for turns, moment in [([1, 2], None), ('just text', None), ([{'who': 'alien', 'text': 5}], None), ([{'who': 'customer', 'text': 'stop'}], 7)]:
        with pytest.raises(ValidationError):
            ExamCase(channel='text', turns=turns, expected='opted_out', moment=moment).full_clean()
    ExamCase(channel='text', turns=[{'who': 'customer', 'text': 'stop'}], expected='opted_out', moment=0).full_clean()
