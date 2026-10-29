"""Owner, 2026-10-30, the litigation package full flow: the client asks; staff Accept; the client types the numbers and
CiV makes the package; staff check it and Release with the custodian's name; the client downloads it. All logged."""
import datetime
import io
import uuid
import zipfile

import pytest
from django.core import mail
from django.utils import timezone

from apps.access_log.models import AccessEntry
from apps.contacts.models import ContactEvent
from apps.contacts.normalize import codes_for
from apps.ledger.models import Fingerprint
from apps.reports.models import QuoteRequest
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db
LITIGATION = 'Litigation evidence package'
PHONE = '+19165550142'
WHEN = timezone.now() - datetime.timedelta(days=1)


@pytest.fixture(autouse=True)
def number(company):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    token = codes_for(company).token(PHONE)
    ContactEvent.objects.create(client=company, phone_token=token, phone_token_kid='k1', source_system='vicidial', source_record_id='call-1',
                                source_grade='B', channel='call', direction='outbound', occurred_at=WHEN, masked_label='(916) •••-0142')
    Fingerprint.objects.create(client=company, job_id=uuid.uuid4(), source_system='vicidial', source_record_id='call-1', content_kind='call',
                               source_grade='B', sha256='e' * 64, fetched_at=WHEN)


@pytest.fixture
def staff(client):
    boss = StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD)
    client.force_login(boss)
    return boss


def step(client, q, name, **form):
    return client.post(f'/civ-admin/reports/quoterequest/{q.pk}/step/{name}/', form)


def card(api):
    return next(t for t in api.get('/api/reports').json()['types'] if t['name'] == LITIGATION)


def test_the_full_flow(client, staff, company, admin_user, signed_in):
    api = signed_in(admin_user)
    api.call('post', '/api/reports', {'name': LITIGATION, 'period': 'Sep 2026'})
    q = QuoteRequest.objects.get()
    # Before CiV accepts, numbers are refused.
    assert api.call('post', '/api/reports/litigation', {'numbers': [PHONE]}).status_code == 409

    assert 'Accept (price agreed)' in client.get(f'/civ-admin/reports/quoterequest/{q.pk}/change/').content.decode()
    step(client, q, 'accept', note='Price $500 agreed by phone')
    q.refresh_from_db()
    assert q.status == 'accepted' and q.note == 'Price $500 agreed by phone'
    assert card(api)['quote']['step'] == 'accepted'
    assert mail.outbox[-1].to == [admin_user.email]

    made = api.call('post', '/api/reports/litigation', {'numbers': [PHONE, '+14805550923']})
    assert made.status_code == 201 and made.json()['found'] == 1 and made.json()['missing'] == 1
    q.refresh_from_db()
    assert q.status == 'checking' and q.package and PHONE not in str(QuoteRequest.objects.values().get())
    assert mail.outbox[-1].to == ['boss@complyiv.com']
    z = zipfile.ZipFile(io.BytesIO(q.package.read()))
    names = z.namelist()
    assert any(n.startswith('chain-of-custody/') for n in names) and 'certification/fingerprint-list.csv' in names
    assert 'certification/custodian-declaration.txt' not in names
    custody = z.read(next(n for n in names if n.startswith('chain-of-custody/'))).decode()
    assert 'vicidial' in custody and 'e' * 64 in custody
    # The client cannot download it before staff release it.
    assert api.get(f'/api/reports/quote-{q.pk}/file').status_code == 404
    assert client.get(f'/civ-admin/reports/quoterequest/{q.pk}/download/').status_code == 200

    assert 'Release to the client' in client.get(f'/civ-admin/reports/quoterequest/{q.pk}/change/').content.decode()
    step(client, q, 'release')  # no custodian yet: refused
    q.refresh_from_db()
    assert q.status == 'checking'
    step(client, q, 'release', custodian_name='Sam Hale', custodian_title='Records custodian')
    q.refresh_from_db()
    assert q.status == 'released' and q.released_by == 'boss@complyiv.com'
    assert mail.outbox[-1].to == [admin_user.email]

    page = api.get('/api/reports').json()
    assert page['runs'][0]['status'] == 'ready' and card(api)['released']['url'] == f'/api/reports/quote-{q.pk}/file'
    assert card(api)['quote'] is None  # the client may ask for another
    got = api.get(f'/api/reports/quote-{q.pk}/file')
    assert got.status_code == 200 and got['Content-Type'] == 'application/zip'
    declaration = zipfile.ZipFile(io.BytesIO(b''.join(got.streaming_content))).read('certification/custodian-declaration.txt').decode()
    assert 'Sam Hale' in declaration and 'Records custodian' in declaration and 'DRAFT' not in declaration
    assert company.name in declaration
    package = zipfile.ZipFile(io.BytesIO(q.package.read()))
    for name in package.namelist():  # every text in the package names the client (owner, 2026-10-30)
        if name.endswith(('.txt', '.csv')):
            assert company.name in package.read(name).decode(), name
    actions = set(AccessEntry.objects.values_list('action', flat=True))
    assert {'quote_requested', 'quote_request_accepted', 'litigation_package_made', 'litigation_package_released',
            'litigation_package_downloaded'} <= actions


def test_only_an_admin_or_the_lawyer_sends_numbers(client, staff, company, member_user, admin_user, signed_in):
    signed_in(admin_user).call('post', '/api/reports', {'name': LITIGATION, 'period': 'Sep 2026'})
    step(client, QuoteRequest.objects.get(), 'accept')
    assert signed_in(member_user).call('post', '/api/reports/litigation', {'numbers': [PHONE]}).status_code == 403


def test_another_company_never_sees_the_package(client, staff, company, admin_user, other_admin, signed_in):
    signed_in(admin_user).call('post', '/api/reports', {'name': LITIGATION, 'period': 'Sep 2026'})
    q = QuoteRequest.objects.get()
    step(client, q, 'accept')
    signed_in(admin_user).call('post', '/api/reports/litigation', {'numbers': [PHONE]})
    step(client, q, 'release', custodian_name='Sam Hale', custodian_title='Records custodian')
    other = signed_in(other_admin)
    assert other.get(f'/api/reports/quote-{q.pk}/file').status_code == 404
    assert other.call('post', '/api/reports/litigation', {'numbers': [PHONE]}).status_code == 409


def test_no_save_buttons_and_done_keeps_the_note(client, staff, company, admin_user, signed_in):
    """Owner, 2026-10-30 (option C): no Save buttons on a quote request; the step buttons keep the note."""
    signed_in(admin_user).call('post', '/api/reports', {'name': LITIGATION, 'period': 'Sep 2026'})
    q = QuoteRequest.objects.get()
    page = client.get(f'/civ-admin/reports/quoterequest/{q.pk}/change/').content.decode()
    assert 'Save and continue editing' not in page and 'name="_save"' not in page and 'Mark done (client contacted)' in page
    step(client, q, 'done', note='Client said no to the price')
    q.refresh_from_db()
    assert q.done_at is not None and q.note == 'Client said no to the price'
    step(client, q, 'accept', note='changed later')
    q.refresh_from_db()
    assert q.status == 'asked' and q.note == 'Client said no to the price'
