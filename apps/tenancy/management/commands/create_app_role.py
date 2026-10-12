"""Makes (or refreshes) the limited database user the app runs as. Run as the owner; safe to run on every deploy.
It cannot skip the tenancy lock (no superuser, no BYPASSRLS) and cannot create or change tables."""
import os

from django.core.management.base import BaseCommand
from django.db import connection
from psycopg import sql


class Command(BaseCommand):
    help = 'Create the limited database user named in DB_APP_USER (password DB_APP_PASSWORD).'

    def handle(self, *args, **options):
        user, password = os.environ.get('DB_APP_USER', ''), os.environ.get('DB_APP_PASSWORD', '')
        if not user or not password:
            self.stdout.write('DB_APP_USER / DB_APP_PASSWORD not set: nothing to do.')
            return
        role, db, owner = sql.Identifier(user), sql.Identifier(connection.settings_dict['NAME']), sql.Identifier(connection.get_connection_params()['user'])
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1 FROM pg_roles WHERE rolname = %s', [user])
            verb = 'ALTER' if cursor.fetchone() else 'CREATE'
            statements = [
                sql.SQL(verb + ' ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE').format(role, sql.Literal(password)),
                sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(db, role),
                sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(role),
                sql.SQL('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}').format(role),
                sql.SQL('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(role),
                # Tables added by later migrations get the same rights.
                sql.SQL('ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}').format(owner, role),
                sql.SQL('ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {}').format(owner, role),
            ]
            for statement in statements:
                cursor.execute(statement.as_string(cursor.connection))
        self.stdout.write(f'Limited database user "{user}" is ready.')
