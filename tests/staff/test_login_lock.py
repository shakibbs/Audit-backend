"""Owner decision 2026-10-23: the staff panel locks an email after 5 wrong passwords in 15 minutes, like the portal."""
from datetime import timedelta

import pytest
from django.test import Client as Browser

from apps.access_log.models import AccessEntry
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db
LOGIN = '/civ-admin/login/?next=/civ-admin/'


def sign_in(b, password, email='team@complyiv.com'):
    return b.post(LOGIN, {'username': email, 'password': password})


def test_five_wrong_passwords_lock_the_staff_email_for_15_minutes(monkeypatch):
    StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD)
    b = Browser()
    for _ in range(5):
        assert sign_in(b, 'wrong-password').status_code == 200
    locked = sign_in(b, PASSWORD)
    assert locked.status_code == 200 and 'Too many wrong tries' in locked.content.decode()  # even the right password
    assert AccessEntry.objects.filter(action='staff_sign_in_failed', object='team@complyiv.com').count() == 5
    from types import SimpleNamespace

    from django.utils import timezone

    from apps.accounts import lockout
    later = timezone.now() + timedelta(minutes=16)
    monkeypatch.setattr(lockout, 'timezone', SimpleNamespace(now=lambda: later))  # 16 minutes pass
    assert sign_in(b, PASSWORD).status_code == 302  # after 15 minutes it works again


def test_a_portal_lock_does_not_lock_the_staff_panel_or_the_other_way():
    StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD)
    for _ in range(5):
        Browser().post('/api/session/sign-in', {'email': 'team@complyiv.com', 'password': 'x'}, content_type='application/json')
    assert sign_in(Browser(), PASSWORD).status_code == 302


def test_staff_pages_show_readable_names_not_object_numbers(company):
    """Bug fix 2026-10-23: "Report object (21)", "BuyerInvite object (1)", "ExamCase object (2)"."""
    from datetime import date

    from apps.buyers.models import BuyerInvite, BuyerOrg
    from apps.conversations.models import ExamCase
    from apps.reports.models import Report
    report = Report.objects.create(client=company, name='Period audit report', period=date(2026, 9, 1), status='ready')
    org = BuyerOrg.objects.create(name='Falcon Risk', domain='falconrisk.com')
    invite = BuyerInvite.objects.create(org=org, client=company, email='sam@falconrisk.com', invited_by='Dana', token_hash='x' * 64,
                                        expires_at=report.made_at)
    case = ExamCase.objects.create(channel='text', turns=[{'who': 'customer', 'text': 'stop texting me'}], expected='opted_out')
    assert str(report) == f'Period audit report · Sep 2026 · {company}'
    assert str(invite) == f'Invite to sam@falconrisk.com (from {company})'
    assert str(case) == 'Text question: “stop texting me” → opted out'


def test_the_access_log_says_who_in_plain_words(client, company):
    """Bug fix 2026-10-23: automatic rows showed the object (e.g. "k1") as Who; entry pages showed raw codes."""
    from apps.access_log.recorder import record
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    entry = record('client_key_created', client_id=company.pk, object='k1')
    page = client.get('/civ-admin/access_log/accessentry/').content.decode()
    assert 'CiV (automatic)' in page
    one = client.get(f'/civ-admin/access_log/accessentry/{entry.pk}/change/').content.decode()
    assert 'Phone-code key made' in one and 'client_key_created' not in one and 'Actor kind' not in one and company.name in one


def test_dashboard_tiles_say_what_they_count_and_open_the_matching_list(client, company):
    """Bug fix 2026-10-23: numbers that did not add up, and tiles that all opened the plain client list."""
    from apps.connections.models import Connection, Status
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    Connection.objects.create(client=company, provider='vicidial', status=Status.FAILED)
    page = client.get('/civ-admin/').content.decode()
    assert 'Connections working' in page and 'New law items · high priority' in page
    for q in ('?attention=invites', '?attention=connections', '?attention=renewals'):
        assert q in page
    failed = client.get('/civ-admin/clients/client/?attention=connections').content.decode()
    assert company.name in failed


def test_small_files_and_checklist_messages_read_well():
    """Bug fix 2026-10-23: a 193-byte file showed "0 KB"; the checklist said "'First sync done' done."."""
    from pathlib import Path

    from apps.documents.admin import readable_size
    assert (readable_size(193), readable_size(1300), readable_size(3_600_000)) == ('193 bytes', '1.3 KB', '3.4 MB')
    views = Path('apps/onboarding/views.py').read_text()
    assert "Marked done: {label}." in views and "Marked not done: {label}." in views
