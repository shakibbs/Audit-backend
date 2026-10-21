"""Module 11 step 2: the client's Admins and lawyer assign, date, progress, decide (note kept, fingerprint logged) and
dispute a finding; Members only read; every change is in the access log; tips are drafts."""
from datetime import UTC, date, datetime, timedelta

import pytest
from django.utils import timezone

from apps.access_log.models import AccessEntry
from apps.accounts.models import ClientUser
from apps.findings.models import Finding

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 9, 20, tzinfo=UTC)


@pytest.fixture
def finding(company):
    return Finding.objects.create(client=company, key='M10', metric='M10', domain='REV', severity='High', title='Contacts after an opt-out',
                                  why='CiV found 14 contacts.', affected=14, period=date(2026, 9, 1), first_seen=NOW, last_seen=NOW)


def test_admin_assigns_dates_and_progresses(finding, admin_user, member_user, signed_in):
    api = signed_in(admin_user)
    url = f'/api/actions/f-{finding.pk}'
    assert api.call('patch', url, {'assignee': member_user.name}).json()['assignee'] == member_user.name
    late = (timezone.localdate() - timedelta(days=1)).isoformat()
    row = api.call('patch', url, {'due': late}).json()
    assert row['due'] == late and row['overdue'] is True
    row = api.call('patch', url, {'status': 'in_progress'}).json()
    assert row['status'] == 'in_progress' and row['fixStep'].startswith('Companies commonly') and row['fixStepDraft']
    assert api.get('/api/actions').json()[0]['assignee'] == member_user.name


def test_decision_keeps_the_note_and_logs_only_its_fingerprint(finding, admin_user, signed_in):
    row = signed_in(admin_user).call('patch', f'/api/actions/f-{finding.pk}', {'decision': {'choice': 'accepted', 'note': 'Reviewed with counsel.'}}).json()
    assert row['decision']['choice'] == 'accepted' and row['decision']['note'] == 'Reviewed with counsel.' and row['decision']['by'] == admin_user.name
    entry = AccessEntry.objects.filter(action='finding_changed').get()
    assert 'Reviewed with counsel' not in entry.object and 'note sha256' in entry.object
    assert len(Finding.objects.get().note_sha256) == 64


def test_dispute_is_shown_with_who_and_when(finding, admin_user, signed_in):
    row = signed_in(admin_user).call('patch', f'/api/actions/f-{finding.pk}', {'dispute': {'note': 'Those were appointment reminders.'}}).json()
    assert row['dispute'] == {'note': 'Those were appointment reminders.', 'by': admin_user.name, 'at': timezone.localdate().isoformat()}


def test_members_only_read_but_the_lawyer_can_decide(finding, company, member_user, signed_in, api):
    assert signed_in(member_user).call('patch', f'/api/actions/f-{finding.pk}', {'status': 'resolved'}).status_code == 403
    member_user.is_counsel = True
    member_user.save()
    assert api.call('patch', f'/api/actions/f-{finding.pk}', {'status': 'resolved'}).status_code == 200


def test_bad_input_and_other_companies(finding, admin_user, signed_in, other_company):
    api = signed_in(admin_user)
    stranger = ClientUser.objects.create_user(client=other_company, email='x@ridge.com', name='Other Person', password='a-long-test-password-1')
    assert api.call('patch', f'/api/actions/f-{finding.pk}', {'assignee': stranger.name}).status_code == 400
    assert api.call('patch', f'/api/actions/f-{finding.pk}', {'decision': {'choice': 'maybe'}}).status_code == 400
    assert api.call('patch', f'/api/actions/f-{finding.pk}', {}).status_code == 400
    other = Finding.objects.create(client=other_company, key='M10', metric='M10', domain='REV', severity='High', title='t', why='w',
                                   period=date(2026, 9, 1), first_seen=NOW, last_seen=NOW)
    assert api.call('patch', f'/api/actions/f-{other.pk}', {'status': 'resolved'}).status_code == 404


def test_civ_closing_a_finding_wins_over_the_clients_status(finding, admin_user, signed_in):
    Finding.objects.filter(pk=finding.pk).update(status='resolved', resolved_at=NOW, work_status='in_progress')
    row = signed_in(admin_user).get('/api/actions').json()[0]
    assert row['status'] == 'resolved' and row['resolvedOn'] == '2026-09-20'
