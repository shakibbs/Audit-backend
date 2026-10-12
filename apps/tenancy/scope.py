"""Tells the database whose rows this work may see. Locked tables show nothing until a scope is set.

    with tenant(client): ...       one client's rows only (jobs and, later, portal requests)
    with all_clients(): ...        every client's rows (CiV's own nightly jobs)
"""
from contextlib import contextmanager

from django.db import connection

_READ = "SELECT current_setting('civ.scope', true), current_setting('civ.client_id', true)"
_SET = "SELECT set_config('civ.scope', %s, false), set_config('civ.client_id', %s, false)"


@contextmanager
def _scope(scope: str, client_id: str):
    with connection.cursor() as cursor:
        cursor.execute(_READ)
        before = cursor.fetchone()
        cursor.execute(_SET, [scope, client_id])
    try:
        yield
    finally:  # always put back what was there, so a scope never leaks into the next piece of work
        with connection.cursor() as cursor:
            cursor.execute(_SET, [before[0] or '', before[1] or ''])


def tenant(client):
    return _scope('client', str(getattr(client, 'pk', client)))


def all_clients():
    return _scope('all', '')
