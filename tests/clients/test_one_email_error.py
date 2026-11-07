"""Owner, 2026-11-07: a bad Admin email on Add client shows one message, not two."""
import pytest

from apps.staff.models import StaffUser
from tests.conftest import PASSWORD
from tests.connections.test_connections import company_fields, management

pytestmark = pytest.mark.django_db


def post(client, email):
    data = {**company_fields(), 'admin_name': 'Dana Ruiz', 'admin_email': email,
            **management('connections', 0), **management('contract', 0), **management('documents', 0)}
    return client.post('/civ-admin/clients/client/add/', data).content.decode()


def test_one_message_for_the_admin_email(client):
    client.force_login(StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD))
    bad = post(client, 'dana@')
    assert 'Enter a valid email address.' in bad and "Enter the client Admin&#x27;s email." not in bad
    empty = post(client, '')
    assert "Enter the client Admin&#x27;s email." in empty and 'Enter a valid email address.' not in empty
