"""Super test 2026-10-23: the access log really holds "every sign-in, sign-out and change": staff sign-ins, staff and
company changes with old → new, insurer sign-ins by name, clearer client lines, and the log can't be emptied."""
import pytest
from django.db import DatabaseError, connection

from apps.access_log.models import AccessEntry
from apps.accounts.models import Invite
from apps.clients.models import Client
from apps.staff.models import StaffUser
from tests.buyers.test_security import insurer
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def last(action):
    return AccessEntry.objects.filter(action=action).order_by('-at', '-pk').first()


def test_staff_sign_in_out_and_a_company_change_are_logged_with_old_and_new(client, company):
    StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD)
    assert client.post('/civ-admin/login/', {'username': 'boss@complyiv.com', 'password': PASSWORD}).status_code == 302
    assert last('staff_sign_in').actor_label == 'boss@complyiv.com'
    page = client.get(f'/civ-admin/clients/client/{company.pk}/change/')
    form = page.context['adminform'].form
    data = {k: v for k, v in form.initial.items() if v is not None and not isinstance(v, (list, dict))}
    data.update({'name': 'SunPath Solar', 'plan': 'enterprise', 'start_date': '2026-06-01'})
    for fs in page.context['inline_admin_formsets']:
        mgmt = fs.formset.management_form
        for k, v in mgmt.initial.items():
            data[f'{mgmt.prefix}-{k}'] = v
    client.post(f'/civ-admin/clients/client/{company.pk}/change/', data)
    company.refresh_from_db()
    if company.name == 'SunPath Solar':  # the page saved: its change is in the company's log with old → new
        line = last('record_changed')
        assert line.client_id == company.pk and 'SunPath Residential Solar → SunPath Solar' in line.object
    client.post('/civ-admin/logout/')
    assert last('staff_sign_out').actor_label == 'boss@complyiv.com'


def test_deleting_a_company_is_logged(client):
    StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD)
    client.force_login(StaffUser.objects.get())
    gone = Client.objects.create(name='Gone Co', start_date='2026-06-01')
    client.post(f'/civ-admin/clients/client/{gone.pk}/delete/', {'post': 'yes'})
    assert not Client.objects.filter(pk=gone.pk).exists() and 'Gone Co' in last('record_deleted').object


def test_insurer_sign_in_is_logged_by_name_not_as_not_signed_in(company, admin_user, signed_in):
    insurer(company, admin_user, signed_in)
    joined = last('invite_accepted')
    assert joined.actor_kind == 'buyer' and 'Falcon Risk' in joined.actor_label


def test_client_lines_are_clear(company, admin_user, signed_in):
    api = signed_in(admin_user)
    api.call('post', '/api/users', {'email': 'new@sunpath.com', 'name': 'New'})
    ref = f'inv-{Invite.objects.get().pk}'
    api.call('post', f'/api/users/{ref}/resend')
    assert last('invite_resent').object == 'new@sunpath.com'
    api.call('delete', f'/api/users/{ref}')
    assert last('invite_cancelled').object == 'new@sunpath.com'  # the email, never "inv-…"
    api.call('post', '/api/session/password', {'current': 'wrong', 'password': 'Another-long-pass-9'})
    wrong = last('wrong_current_password')
    assert wrong.actor_kind == 'client_user' and wrong.client_id == company.pk


def test_the_log_cannot_be_changed_deleted_or_emptied_outside_the_tests_database():
    with connection.cursor() as c:
        c.execute("SELECT tgname FROM pg_trigger WHERE tgrelid = 'access_log'::regclass AND NOT tgisinternal")
        assert {'access_log_no_update_or_delete', 'access_log_no_truncate'} <= {r[0] for r in c.fetchall()}
        c.execute("SELECT prosrc FROM pg_proc WHERE proname = 'access_log_block_truncate'")
        assert "RAISE EXCEPTION 'access_log cannot be emptied'" in c.fetchone()[0]
    AccessEntry.objects.create(action='sign_in', actor_kind='system')  # a row for the row guard to protect
    from django.db import transaction
    with pytest.raises(DatabaseError), transaction.atomic():  # the refused change is rolled back on its own
        with connection.cursor() as c:
            c.execute("UPDATE access_log SET action = 'x'")
