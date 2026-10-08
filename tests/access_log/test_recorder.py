import pytest

from apps.access_log.models import AccessEntry
from apps.access_log.recorder import record


@pytest.mark.django_db
def test_record_writes_a_row():
    entry = record('sign_in', actor_kind='client_user', actor_id=7, actor_label='a@b.com', client_id=3)
    assert AccessEntry.objects.get(pk=entry.pk).action == 'sign_in'


@pytest.mark.django_db
def test_rows_cannot_be_changed_or_deleted():
    entry = record('sign_in')
    entry.action = 'something_else'
    with pytest.raises(PermissionError):
        entry.save()
    with pytest.raises(PermissionError):
        entry.delete()


@pytest.mark.django_db(transaction=True)
def test_database_refuses_bulk_changes():
    from django.db import DatabaseError
    record('sign_in')
    with pytest.raises(DatabaseError):
        AccessEntry.objects.update(action='changed')
