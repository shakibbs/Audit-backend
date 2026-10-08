import datetime

import pytest

from apps.clients.models import Client


@pytest.mark.django_db
def test_new_client_starts_in_lawyer_only_mode():
    client = Client.objects.create(name='SunPath Residential Solar', start_date=datetime.date(2026, 6, 1))
    assert client.counsel_directed is True
    assert client.is_active is True
