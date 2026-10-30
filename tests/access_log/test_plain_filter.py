"""Owner, 2026-10-31: the Access log's "What" filter shows plain words, A–Z, never codes like sign_in_failed."""
import pytest

from apps.access_log.recorder import record
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_the_what_filter_reads_plainly(client):
    for action in ('sign_in_failed', 'buyer_link_granted', 'quote_request_accepted'):
        record(action)
    client.force_login(StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD))
    page = client.get('/civ-admin/access_log/accessentry/').content.decode()
    assert 'Failed sign-in' in page and 'Quote accepted' in page
    assert '>sign_in_failed<' not in page and '>quote_request_accepted<' not in page
    only = client.get('/civ-admin/access_log/accessentry/?action__exact=sign_in_failed').content.decode()
    assert only.count('Failed sign-in') >= 2  # the filter choice and the one row
