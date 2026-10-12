"""Tenancy lock: the database itself shows a client's rows only inside that client's scope."""
import pytest
from django.db import DatabaseError, connection, transaction

from apps.ledger.models import ContentKind, SourceGrade
from apps.ledger.record import ledger_job
from apps.tenancy.scope import _scope, all_clients, tenant

# CiV's own business records (companies, users, contracts…): read across clients by the admin panel, not locked here.
BUSINESS_TABLES = {'access_log', 'client_document', 'client_invite', 'client_status_change', 'client_user',
                   'connection', 'contract', 'onboarding_tick'}


def as_limited_user():
    """Superusers skip every lock (as on CI), so act as a plain user for the rest of this test's transaction."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT rolsuper FROM pg_roles WHERE rolname = current_user')
        if cursor.fetchone()[0]:
            cursor.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'civ_lock_probe') "
                           "THEN CREATE ROLE civ_lock_probe NOLOGIN; END IF; END $$;")
            cursor.execute('GRANT SELECT, INSERT ON fingerprint TO civ_lock_probe')
            cursor.execute('GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO civ_lock_probe')
            cursor.execute('SET LOCAL ROLE civ_lock_probe')


def count(sql='SELECT client_id FROM fingerprint'):
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return sorted(r[0] for r in cursor.fetchall())


def read_one(client):
    with ledger_job(client, 'twilio sync') as job:
        job.record(source_system='twilio', source_record_id='SM1', raw=b'x', content_kind=ContentKind.TEXT, source_grade=SourceGrade.C)


@pytest.mark.django_db
def test_each_client_sees_only_its_own_rows(company, other_company):
    read_one(company)
    read_one(other_company)
    as_limited_user()
    with tenant(company):
        assert count() == [company.pk]
    with tenant(other_company):
        assert count() == [other_company.pk]
    with all_clients():
        assert count() == sorted([company.pk, other_company.pk])


@pytest.mark.django_db
def test_no_scope_sees_nothing(company):
    read_one(company)
    as_limited_user()
    with _scope('', ''):
        assert count() == []
        assert count(f'SELECT client_id FROM fingerprint WHERE client_id = {company.pk}') == []  # even when asked directly


@pytest.mark.django_db
def test_cannot_write_a_row_for_another_client(company, other_company):
    as_limited_user()
    with tenant(company), pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("INSERT INTO fingerprint (client_id, job_id, source_system, source_record_id, content_kind, "
                       "source_grade, sha256, fetched_at) VALUES (%s, gen_random_uuid(), 'twilio', 'SM9', 'text', 'C', %s, now())",
                       [other_company.pk, '0' * 64])


@pytest.mark.django_db
def test_scope_is_put_back_afterwards(company):
    with _scope('', ''):
        with tenant(company):
            pass
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('civ.scope', true), current_setting('civ.client_id', true)")
            assert cursor.fetchone() == ('', '')


@pytest.mark.django_db
def test_every_table_with_client_data_is_locked():
    with connection.cursor() as cursor:
        cursor.execute("SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
                       "JOIN information_schema.columns col ON col.table_name = c.relname AND col.column_name = 'client_id' "
                       "WHERE col.table_schema = 'public' AND c.relkind = 'r'")
        tables = cursor.fetchall()
    unlocked = [name for name, rls, force in tables if not (rls and force) and name not in BUSINESS_TABLES]
    assert unlocked == [], f'Lock these tables with apps.tenancy.sql.lock_table: {unlocked}'
    assert {'client_key', 'fingerprint', 'purge_log', 'merkle_anchor'} <= {n for n, rls, force in tables if rls and force}


@pytest.mark.django_db
def test_jobs_set_their_own_scope(company, monkeypatch):
    """Phone codes, fingerprints and the seal work from a blank scope: none of them relies on the caller."""
    import datetime

    from django.utils import timezone

    from apps.anchoring import stamps
    from apps.anchoring.seal import seal_finished_days, verify
    from apps.keyring.tokens import Tokenizer
    from apps.ledger.models import Fingerprint
    monkeypatch.setattr(stamps, 'tsa_stamp', lambda root: ('https://tsa.test', b'signed', timezone.now()))
    monkeypatch.setattr(stamps, 'ots_stamp', lambda root: ('https://ots.test', b'pending'))
    with _scope('', ''):
        assert Tokenizer(company).token('9165554471')
        read_one(company)
        Fingerprint.objects.update(fetched_at=timezone.now() - datetime.timedelta(days=1))  # sees nothing: blank scope
        with all_clients():
            Fingerprint.objects.update(fetched_at=timezone.now() - datetime.timedelta(days=1))
        assert len(seal_finished_days()) == 1
        with all_clients():
            fp = Fingerprint.objects.get(client=company)
        assert verify(fp) == 'matches'


def test_limited_user_command_does_nothing_without_settings(monkeypatch, capsys):
    from django.core.management import call_command
    monkeypatch.delenv('DB_APP_USER', raising=False)
    call_command('create_app_role')
    assert 'nothing to do' in capsys.readouterr().out
