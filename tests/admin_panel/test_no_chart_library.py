"""Owner, 2026-11-16: staff panel pages do not load the chart library (no page draws a chart; it held up every page)."""
import pytest

from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_no_chart_library_and_no_chart_on_any_page(client, company):
    assert 'chart/chart' not in client.get('/civ-admin/login/').content.decode()
    client.force_login(StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD))
    for url in ('/civ-admin/', f'/civ-admin/clients/client/{company.pk}/change/', '/civ-admin/access_log/accessentry/'):
        page = client.get(url).content.decode()
        assert 'chart/chart' not in page and 'class="chart' not in page, url
        assert 'unfold/js/app' in page  # the rest of the page is unchanged
