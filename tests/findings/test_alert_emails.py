"""Owner decision 2026-10-23: alert emails go to the company's active Admins only, once per alert (and again if it
comes back), for the alert types the Admin chose in Settings → Notifications; choices and setup ticks are saved per
company in the backend, not the portal's sample."""
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.alerts.models import Alert
from apps.alerts.raise_ import refresh
from apps.connections.models import Connection, Status
from tests.findings.test_alerts import after_stop

pytestmark = pytest.mark.django_db


def test_a_new_alert_emails_the_admins_once(company, admin_user, member_user):
    now = timezone.now()
    after_stop(company, now - timedelta(hours=2))
    refresh(company, now)
    assert len(mail.outbox) == 1 and mail.outbox[0].to == [admin_user.email]  # Admins only, not the Member
    assert mail.outbox[0].subject.startswith('[High]') and '/alerts' in mail.outbox[0].body
    after_stop(company, now - timedelta(hours=1))
    refresh(company, now)  # same alert updated: no second email
    assert len(mail.outbox) == 1 and Alert.objects.get().emailed_at


def test_a_returning_alert_emails_again_and_a_type_switched_off_does_not(company, admin_user, signed_in, api):
    tool = Connection.objects.create(client=company, provider='vicidial', status=Status.STALE)
    refresh(company)
    tool.status = Status.CONNECTED
    tool.save()
    refresh(company)
    tool.status = Status.STALE
    tool.save()
    refresh(company)
    assert len(mail.outbox) == 2  # appeared, resolved, came back
    signed_in(admin_user)
    assert api.call('patch', '/api/settings/email/notifications', {'kind': 'source-stale', 'email': False}).json()['email'] is False
    tool.status = Status.CONNECTED
    tool.save()
    refresh(company)
    tool.status = Status.STALE
    tool.save()
    refresh(company)
    assert len(mail.outbox) == 2  # switched off: no email, still in the portal
    choice = next(n for n in api.call('get', '/api/settings').json()['notifications'] if n['kind'] == 'source-stale')
    assert choice['email'] is False


def test_only_the_admin_changes_choices_and_ticks(company, admin_user, member_user, signed_in, api):
    signed_in(member_user)
    assert api.call('patch', '/api/settings/email/notifications', {'kind': 'vendor-drop', 'email': True}).status_code == 403
    assert api.call('patch', '/api/setup/outcomes', {'done': True}).status_code == 403
    signed_in(admin_user)
    assert api.call('patch', '/api/setup/outcomes', {'done': True}).json() == {'id': 'outcomes', 'done': True}
    assert api.call('patch', '/api/setup/nonsense', {'done': True}).status_code == 404
    rows = {r['id']: r for r in api.call('get', '/api/readiness').json()['setup']}
    assert rows['outcomes']['done'] and 'Marked done by' in rows['outcomes']['count']
    assert rows['optout-methods'] == {'id': 'optout-methods', 'done': False, 'count': 'Not marked yet', 'label': 'Designated opt-out methods',
                                      'detail': 'Whether you designate an exclusive opt-out method, and where it is disclosed'}


def test_ticks_and_choices_are_per_company(company, other_company, admin_user, other_admin, signed_in, api):
    signed_in(admin_user)
    api.call('patch', '/api/setup/outcomes', {'done': True})
    api.call('patch', '/api/settings/email/notifications', {'kind': 'page-change', 'email': False})
    signed_in(other_admin)
    rows = {r['id']: r for r in api.call('get', '/api/readiness').json()['setup']}
    assert rows['outcomes']['done'] is False
    assert next(n for n in api.call('get', '/api/settings').json()['notifications'] if n['kind'] == 'page-change')['email'] is True
