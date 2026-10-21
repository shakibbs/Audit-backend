"""Module 14 step 4: legal holds — placed and released by Admins and the lawyer, seen by everyone; a held number,
vendor or date range keeps its files past the 4-year deletion; the number page says so."""
import datetime

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.contacts.api import number_ref
from apps.contacts.models import ContactEvent
from apps.contacts.normalize import codes_for
from apps.evidence.holds import parse_dates
from apps.evidence.models import LegalHold
from apps.provenance.models import ProofRequest
from apps.provenance.requests import purge_old as purge_proofs
from apps.vendors.contracts import purge_old as purge_contracts
from apps.vendors.models import VendorContract

pytestmark = pytest.mark.django_db
PHONE = '+19165550142'
OLD = timezone.now() - datetime.timedelta(days=5 * 365)


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def place(api, scope, target, reason='Smith v. SunPath, 2026-1234'):
    return api.call('post', '/api/legal-holds', {'scope': scope, 'target': target, 'reason': reason})


def test_dates_are_read_in_either_form():
    assert parse_dates('2026-01-01 to 2026-03-31') == (datetime.date(2026, 1, 1), datetime.date(2026, 3, 31))
    assert parse_dates('1/1/2026 – 3/31/2026') == (datetime.date(2026, 1, 1), datetime.date(2026, 3, 31))
    assert parse_dates('2026-03-31 to 2026-01-01') is None and parse_dates('soon') is None


def test_place_see_and_release(company, admin_user, member_user, signed_in):
    api = signed_in(admin_user)
    made = place(api, 'number', PHONE).json()
    assert made['target'] == '(916) •••-0142' and PHONE not in str(LegalHold.objects.values())
    assert LegalHold.objects.get().phone_token == codes_for(company).token(PHONE)
    assert place(api, 'date range', 'soon').status_code == 400
    member = signed_in(member_user)
    assert len(member.get('/api/legal-holds').json()) == 1  # everyone sees them
    assert place(member, 'vendor', 'SolarLeads Inc').status_code == 403
    assert member.call('post', f"/api/legal-holds/{made['id']}/release").status_code == 403
    released = signed_in(admin_user).call('post', f"/api/legal-holds/{made['id']}/release").json()
    assert released['releasedOn']


def test_the_number_page_says_under_legal_hold(company, admin_user, signed_in):
    token = codes_for(company).token(PHONE)
    ContactEvent.objects.create(client=company, phone_token=token, phone_token_kid='k1', source_system='vicidial', source_record_id='c1',
                                source_grade='B', channel='call', direction='outbound', occurred_at=timezone.now(), masked_label='(916) •••-0142')
    api = signed_in(admin_user)
    assert api.get(f'/api/evidence/{number_ref(token)}').json()['onHold'] is False
    place(api, 'number', PHONE)
    assert api.get(f'/api/evidence/{number_ref(token)}').json()['onHold'] is True


def test_held_files_survive_the_four_year_deletion(company, admin_user, signed_in):
    token = codes_for(company).token(PHONE)
    proof = ProofRequest.objects.create(client=company, batch_key='b', batch_label='l', batch_size=1, phone_token=token, due_at=OLD,
                                        answer='proof', answered_at=OLD)
    proof.file.save('proof.pdf', ContentFile(b'%PDF'))
    contract = VendorContract(client=company, key='solarleads inc', name='SolarLeads Inc', original_name='t.pdf', sha256='a' * 64, uploaded_by='Dana')
    contract.file.save('t.pdf', ContentFile(b'%PDF'))
    VendorContract.objects.filter(pk=contract.pk).update(uploaded_at=OLD)
    api = signed_in(admin_user)
    place(api, 'number', PHONE)
    place(api, 'vendor', 'solarleads  INC')
    assert purge_proofs() == 0 and purge_contracts() == 0
    for hold in LegalHold.objects.all():
        api.call('post', f'/api/legal-holds/lh-{hold.pk}/release')
    assert purge_proofs() == 1 and purge_contracts() == 1


def test_a_date_range_hold(company, admin_user, signed_in):
    contract = VendorContract(client=company, key='x', name='X', original_name='t.pdf', sha256='a' * 64, uploaded_by='Dana')
    contract.file.save('t.pdf', ContentFile(b'%PDF'))
    VendorContract.objects.filter(pk=contract.pk).update(uploaded_at=OLD)
    place(signed_in(admin_user), 'date range', f'{(OLD - datetime.timedelta(days=1)):%Y-%m-%d} to {(OLD + datetime.timedelta(days=1)):%Y-%m-%d}')
    assert purge_contracts() == 0
