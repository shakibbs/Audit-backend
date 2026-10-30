"""Module 8 step 4: proof requests. A fixed sample per uploaded list, answered by the client's Admin or lawyer,
files kept privately and checked by CiV staff; weak until checked, real proof once valid."""
from datetime import UTC, date, datetime, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.access_log.models import AccessEntry
from apps.consent.checks import check_contact
from apps.consent.keeping import run_rechecks
from apps.consent.models import ConsentProof, ConsentResult
from apps.consent.needs import work_out
from apps.contacts.epochs import epoch_for
from apps.contacts.models import ContactEvent
from apps.imports.models import CrmCreation, ImportBatch
from apps.provenance.models import ProofRequest
from apps.provenance.requests import purge_old, rates, review, send
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD
from tests.regulatory.test_portal_api import browser_for

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 10, 6, 16, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def setup(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    load(RULEBOOK_DIR / 'v3.0.yaml')


def upload(client, size, called=None, start=T0 - timedelta(days=10)):
    batch = ImportBatch.objects.create(client=client, source_system='salesforce', created_by='005U', starts=start, ends=start,
                                       created_count=size, kind='bulk_import')
    CrmCreation.objects.bulk_create([CrmCreation(client=client, source_system='salesforce', record_id=f'leads:{start:%j}{i}', created_at=start,
                                                 phone_tokens=[f't{i}'], batch=batch) for i in range(size)])
    for i in range(called if called is not None else size):
        ContactEvent.objects.create(client=client, phone_token=f't{i}', phone_token_kid='k1', source_system='convoso', source_record_id=f'c{start:%j}{i}',
                                    source_grade='C', channel='call', direction='outbound', occurred_at=T0, dial_mode='manual',
                                    masked_label=f'(916) •••-{i:04d}', epoch=epoch_for(client.pk, f't{i}', T0))
    return batch


def test_fifty_numbers_without_evidence_are_asked_once_and_always_the_same(company):
    upload(company, 1240, called=300)
    ConsentProof.objects.create(client=company, phone_token='t0', kind='inbound_call', proof_type='inbound_call', captured_at=T0 - timedelta(days=20),
                                source_system='convoso', source_record_id='in0')
    assert send(company) == 50
    asked = set(ProofRequest.objects.values_list('phone_token', flat=True))
    assert 't0' not in asked and all(int(t[1:]) < 300 for t in asked)  # only called numbers with no evidence
    assert send(company) == 0  # once per list
    ProofRequest.objects.all().delete()
    send(company)
    assert set(ProofRequest.objects.values_list('phone_token', flat=True)) == asked  # the same sample again


def test_a_list_over_ten_thousand_gets_a_hundred(company):
    upload(company, 10_050, called=150)
    assert send(company) == 100


def test_only_an_admin_or_the_lawyer_can_answer(company, admin_user, member_user):
    upload(company, 30)
    send(company)
    ref = f'pr-{ProofRequest.objects.first().pk}'
    member = browser_for(member_user)
    assert member.get('/api/proof-requests').json()['canAnswer'] is False
    assert member.call('post', f'/api/proof-requests/{ref}/answer', {'none': True}).status_code == 403
    assert browser_for(admin_user).call('post', f'/api/proof-requests/{ref}/answer', {'none': True}).json()['answer'] == 'none'


def answered_with_file(company, admin_user, name='signed.pdf', kind='signed_form'):
    upload(company, 30)
    send(company)
    req = ProofRequest.objects.order_by('pk').first()
    api = browser_for(admin_user)
    token = api.cookies['csrftoken'].value
    reply = api.post(f'/api/proof-requests/pr-{req.pk}/answer', {'file': SimpleUploadedFile(name, b'%PDF signed by the person'), 'fileType': kind},
                     HTTP_X_CSRFTOKEN=token)
    req.refresh_from_db()
    return req, reply, api


def result_for(req):
    c = ContactEvent.objects.get(phone_token=req.phone_token)
    ConsentResult.objects.filter(contact=c).delete()
    work_out(c)
    check_contact(c)
    return ConsentResult.objects.get(contact=c, variant='strict')


def test_an_attached_file_is_kept_privately_and_makes_the_calls_weak_until_checked(company, admin_user):
    req, reply, api = answered_with_file(company, admin_user)
    assert reply.status_code == 200 and req.answer == 'proof' and req.file and len(req.file_sha256) == 64
    assert b''.join(api.get(f'/api/proof-requests/pr-{req.pk}/file').streaming_content) == b'%PDF signed by the person'
    assert AccessEntry.objects.filter(action='proof_file_opened').exists()
    r = result_for(req)
    assert (r.status, r.primary_code) == ('weak', 'WK_CLIENT_PROOF_UNCHECKED')


def test_a_valid_signed_form_becomes_real_proof_and_counts_in_the_rate(company, admin_user):
    req, _, _ = answered_with_file(company, admin_user)
    review(req, 'team@complyiv.com', valid=True, consent_date=date(2026, 9, 1))
    proof = ConsentProof.objects.get(proof_request=req)
    assert proof.proof_type == 'signed_form' and proof.captured_at.date() == date(2026, 9, 1)
    assert result_for(req).status == 'verified'
    row = rates(company)[0]
    assert (row['asked'], row['attached'], row['valid'], row['rate']) == (30, 1, 1, round(1 / 30, 3))


def test_a_file_that_is_not_valid_leaves_no_proof(company, admin_user):
    req, _, _ = answered_with_file(company, admin_user)
    review(req, 'team@complyiv.com', valid=False, note='Different person')
    assert not ConsentProof.objects.filter(proof_request=req).exists()
    r = result_for(req)
    assert r.status == 'no_proof' and 'NP_NO_EVIDENCE_FOUND' in r.codes
    run_rechecks()


def test_staff_check_files_in_the_admin(company, admin_user, client):
    req, _, _ = answered_with_file(company, admin_user)
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    page = client.get(f'/civ-admin/provenance/proofrequest/{req.pk}/change/')
    assert page.status_code == 200 and 'signed.pdf' in page.content.decode()
    assert client.get(f'/civ-admin/provenance/proofrequest/{req.pk}/file/').status_code == 200
    reply = client.post(f'/civ-admin/provenance/proofrequest/{req.pk}/change/', {'review': 'valid', 'consent_date': '', 'review_note': ''})
    assert 'needs the date' in reply.content.decode()
    client.post(f'/civ-admin/provenance/proofrequest/{req.pk}/change/', {'review': 'valid', 'consent_date': '2026-09-01', 'review_note': 'ok'})
    req.refresh_from_db()
    assert req.review == 'valid' and req.reviewed_by == 'team@complyiv.com'


def test_unsafe_or_huge_files_are_refused(company, admin_user):
    _, reply, _ = answered_with_file(company, admin_user, name='run.exe')
    assert reply.status_code == 400


def test_files_go_after_four_years_and_others_never_see_them(company, admin_user, other_admin):
    req, _, _ = answered_with_file(company, admin_user)
    assert browser_for(other_admin).get(f'/api/proof-requests/pr-{req.pk}/file').status_code == 404
    ProofRequest.objects.filter(pk=req.pk).update(answered_at=timezone.now() - timedelta(days=365 * 4 + 2))
    assert purge_old() == 1
    req.refresh_from_db()
    assert not req.file and req.purged_at and req.file_sha256


def test_lead_provenance_follows_the_month(company, admin_user):
    """Owner, 2026-10-30: the month picker — proof requests sent in that month; every card names the month."""
    upload(company, 50)
    send(company)
    sent = ProofRequest.objects.first().sent_at.date()
    month, before = sent.replace(day=1), (sent.replace(day=1) - timedelta(days=1)).replace(day=1)
    api = browser_for(admin_user)
    assert len(api.get(f'/api/proof-requests?period={month:%Y-%m}').json()['requests']) == ProofRequest.objects.count()
    assert api.get(f'/api/proof-requests?period={before:%Y-%m}').json()['requests'] == []
    page = api.get(f'/api/provenance?period={before:%Y-%m}').json()
    assert page['period'] == before.strftime('%B %Y')
    assert api.get(f'/api/leads?period={before:%Y-%m}').status_code == 200
