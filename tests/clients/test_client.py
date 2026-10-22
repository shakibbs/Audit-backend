import datetime

import pytest

from apps.clients.models import Client


@pytest.mark.django_db
def test_a_new_client_is_active():
    client = Client.objects.create(name='SunPath Residential Solar', start_date=datetime.date(2026, 6, 1))
    assert client.is_active is True
