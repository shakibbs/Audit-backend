"""Owner, 2026-10-22: insurers are managed only on the Insurers page — people (password link, turn off), waiting
invitations (Resend, Cancel), companies sharing (Stop sharing), and blocking the whole insurer."""

import pytest
from django.core import mail
from django.utils import timezone

from apps.access_log.models import AccessEntry
from apps.buyers.models import BuyerInvite, BuyerLink, BuyerOrg
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(client):
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    return client


@pytest.fixture
def shared(company, admin_user, signed_in):
    signed_in(admin_user).call('post', '/api/buyer-links', {'name': 'Falcon Risk', 'email': 'a.lee@falconrisk.com', 'person': 'A. Lee'})
    return BuyerOrg.objects.get()


def test_the_insurer_page_shows_waiting_invitations_and_companies(staff, shared, company):
    page = staff.get(f'/civ-admin/buyers/buyerorg/{shared.pk}/change/').content.decode()
    assert 'Waiting invitations' in page and 'a.lee@falconrisk.com' in page and 'Resend' in page
    assert 'Companies sharing' in page and 'Stop sharing' in page and 'BuyerLink object' not in page


def test_resend_and_cancel_an_insurer_invitation(staff, shared):
    invite = BuyerInvite.objects.get()
    first = invite.token_hash
    staff.post(f'/civ-admin/buyers/buyerorg/{shared.pk}/invites/{invite.pk}/resend/')
    invite.refresh_from_db()
    assert invite.token_hash != first and 'invite=' in mail.outbox[-1].body
    staff.post(f'/civ-admin/buyers/buyerorg/{shared.pk}/invites/{invite.pk}/cancel/')
    assert not BuyerInvite.objects.exists()
    assert AccessEntry.objects.filter(action='buyer_invite_cancel').exists()


def test_staff_stop_a_company_sharing(staff, shared, company):
    link = BuyerLink.objects.get()
    staff.post(f'/civ-admin/buyers/buyerorg/{shared.pk}/links/{link.pk}/stop/')
    link.refresh_from_db()
    assert link.revoked_at and link.revoked_by.startswith('CiV') and not link.active(timezone.localdate())
    assert AccessEntry.objects.filter(action='buyer_link_revoked', client_id=company.pk).exists()


def test_delete_a_person_and_a_whole_insurer(staff, shared, company):
    from apps.buyers.models import BuyerUser
    person = BuyerUser(org=shared, email='kim@falconrisk.com', name='Kim')
    person.set_password(PASSWORD)
    person.save()
    page = staff.get(f'/civ-admin/buyers/buyerorg/{shared.pk}/change/').content.decode()
    assert 'Delete' in page
    confirm = staff.get(f'/civ-admin/buyers/buyerorg/{shared.pk}/delete/')
    assert confirm.status_code == 200  # an "Are you sure?" page first
    done = staff.post(f'/civ-admin/buyers/buyerorg/{shared.pk}/delete/', {'post': 'yes'})
    assert done.status_code == 302
    assert not BuyerOrg.objects.exists() and not BuyerUser.objects.exists() and not BuyerLink.objects.exists()
    assert AccessEntry.objects.filter(action='buyer_deleted', client_id=company.pk, object='Falcon Risk').exists()
