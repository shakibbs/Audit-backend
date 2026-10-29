"""Owner, 2026-10-30: "Request a quote" on the litigation package reaches CiV (staff panel list, email, access log);
the evidence file and certification pack cards no longer add "Not available yet" rows."""
import pytest
from django.core import mail

from apps.access_log.models import AccessEntry
from apps.reports.models import QuoteRequest
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db
LITIGATION = 'Litigation evidence package'


def test_request_a_quote_reaches_civ(company, admin_user, signed_in):
    StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD)
    api = signed_in(admin_user)
    made = api.call('post', '/api/reports', {'name': LITIGATION, 'period': 'Sep 2026'})
    assert made.status_code == 201 and made.json()['status'] == 'requested'
    q = QuoteRequest.objects.get()
    assert q.client == company and q.asked_by_email == admin_user.email and q.done_at is None
    assert AccessEntry.objects.filter(action='quote_requested', client_id=company.pk).count() == 1
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ['boss@complyiv.com'] and company.name in mail.outbox[0].subject
    # Asking again keeps the one open request; the card and the history say when it was asked.
    api.call('post', '/api/reports', {'name': LITIGATION, 'period': 'Sep 2026'})
    assert QuoteRequest.objects.count() == 1 and len(mail.outbox) == 1
    page = api.get('/api/reports').json()
    card = next(t for t in page['types'] if t['name'] == LITIGATION)
    assert card['requestedAt'] is not None
    assert [(r['name'], r['status']) for r in page['runs']] == [(LITIGATION, 'requested')]


def test_a_mail_problem_never_loses_the_request(company, admin_user, signed_in, monkeypatch):
    def broken(q):
        raise OSError('no mail server')
    monkeypatch.setattr('apps.reports.emails.quote_requested', broken)
    assert signed_in(admin_user).call('post', '/api/reports', {'name': LITIGATION, 'period': 'Sep 2026'}).status_code == 201
    assert QuoteRequest.objects.count() == 1


def test_staff_see_and_mark_done(client, company, admin_user, signed_in):
    staff = StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD)
    signed_in(admin_user).call('post', '/api/reports', {'name': LITIGATION, 'period': 'Sep 2026'})
    q = QuoteRequest.objects.get()
    client.force_login(staff)
    page = client.get('/civ-admin/reports/quoterequest/').content.decode()
    assert company.name in page and 'Waiting' in page
    client.post('/civ-admin/reports/quoterequest/', {'action': 'mark_done', '_selected_action': [q.pk]})
    q.refresh_from_db()
    assert q.done_at is not None and q.done_by == 'boss@complyiv.com'
    assert AccessEntry.objects.filter(action='quote_request_done').exists()
    # Once done, the card can be asked again.
    api = signed_in(admin_user)
    assert next(t for t in api.get('/api/reports').json()['types'] if t['name'] == LITIGATION)['requestedAt'] is None


def test_evidence_and_certification_cards_add_no_rows(company, admin_user, signed_in):
    api = signed_in(admin_user)
    for name in ('Evidence file export', 'Certification pack'):
        assert api.call('post', '/api/reports', {'name': name, 'period': 'Sep 2026'}).status_code == 400
    assert api.get('/api/reports').json()['runs'] == []
