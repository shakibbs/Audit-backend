"""Admin client page: the Records completeness tile, and the page it opens with every tool."""
from datetime import date

from django.utils import timezone

import pytest

from apps.reconcile.models import PeriodIntegrity, Reconciliation
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db
OCT = timezone.localdate().replace(day=1)  # the details page shows this month and last


@pytest.fixture
def staff_client(client):
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    return client


def page(staff_client, company):
    response = staff_client.get(f'/civ-admin/clients/client/{company.pk}/change/')
    assert response.status_code == 200
    return response.content.decode()


def month_rows(company):
    PeriodIntegrity.objects.create(client=company, period=OCT, completeness=0.82, incomplete=True, flagged_by=['calls'])
    Reconciliation.objects.create(client=company, period=OCT, measure='texts', source_system='twilio', method='bill', records=990,
                                  independent_total=1000, ratio=0.99)
    Reconciliation.objects.create(client=company, period=OCT, measure='calls', source_system='five9', method='tool_total', records=4100,
                                  independent_total=5000, ratio=0.82, flagged=True)
    Reconciliation.objects.create(client=company, period=OCT, measure='calls', source_system='aircall', method='volume', records=20,
                                  independent_total=21, ratio=20 / 21)
    Reconciliation.objects.create(client=company, period=OCT, measure='days_present', records=21, independent_total=21, ratio=1.0)


def test_not_yet_measured_before_the_first_nightly_check(staff_client, company):
    html = page(staff_client, company)
    assert 'Records completeness' in html and 'not yet measured' in html


def test_the_tile_shows_the_month_overall_and_the_lowest_tool(staff_client, company):
    month_rows(company)
    html = page(staff_client, company)
    when = OCT.strftime('%B %Y')
    assert '82%' in html and f'Incomplete · {when} · 3 tools checked · lowest: Five9 calls' in html
    assert f'/civ-admin/clients/client/{company.pk}/completeness/' in html  # the tile opens the details


def test_not_available_when_no_tool_bills(staff_client, company):
    PeriodIntegrity.objects.create(client=company, period=OCT, completeness=None)
    assert 'not available' in page(staff_client, company)


def test_only_this_clients_numbers_are_shown(staff_client, company, other_company):
    PeriodIntegrity.objects.create(client=other_company, period=OCT, completeness=0.5, incomplete=True)
    html = page(staff_client, company)
    assert 'not yet measured' in html and '50%' not in html


def test_the_details_page_shows_every_tool_how_it_was_checked_and_the_numbers(staff_client, company):
    month_rows(company)
    response = staff_client.get(f'/civ-admin/clients/client/{company.pk}/completeness/')
    html = response.content.decode()
    assert response.status_code == 200 and 'Records completeness' in html and OCT.strftime('%B %Y') in html
    assert 'Twilio' in html and 'Bill' in html and 'CiV read 990 of 1,000 billed' in html and '99%' in html
    assert "Tool&#x27;s own total" in html and 'CiV read 4,100 of 5,000 in Five9' in html and 'Below floor' in html
    assert 'Volume pattern' in html and '20 of 21 working days with records' in html
    assert 'Extra check (not in %)' in html and '21 of 21 working days with any records' in html and 'Incomplete' in html
    assert 'How each tool is checked' not in html  # one table only


def test_the_details_page_before_any_check(staff_client, company):
    html = staff_client.get(f'/civ-admin/clients/client/{company.pk}/completeness/').content.decode()
    assert 'Not yet measured' in html
