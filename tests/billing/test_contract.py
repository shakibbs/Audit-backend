"""Contract & billing tab on a client company's page."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.access_log.models import AccessEntry
from apps.billing.models import Contract, renewals_within
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD


@pytest.fixture
def staff_client(client):
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    return client


def save_page(staff_client, company, contract_fields, existing=None):
    data = {'name': company.name, 'industry': 'Solar', 'plan': 'growth', 'start_date': '2026-10-01',
            'status': company.status, 'counsel_directed': 'on'}
    for prefix in ('connections', 'users', 'invites', 'documents'):
        data.update({f'{prefix}-TOTAL_FORMS': 0, f'{prefix}-INITIAL_FORMS': 0, f'{prefix}-MIN_NUM_FORMS': 0, f'{prefix}-MAX_NUM_FORMS': 1000})
    data.update({'contract-TOTAL_FORMS': 1, 'contract-INITIAL_FORMS': 1 if existing else 0,
                 'contract-MIN_NUM_FORMS': 0, 'contract-MAX_NUM_FORMS': 1})
    row = {'currency': 'USD', 'billing_period': 'monthly', 'payment_method': 'invoice', 'notice_days': 30,
           'auto_renew': 'on', **contract_fields}
    if existing:
        row.update({'id': existing.pk, 'client': company.pk})
    data.update({f'contract-0-{k}': v for k, v in row.items()})
    response = staff_client.post(f'/civ-admin/clients/client/{company.pk}/change/', data)
    assert response.status_code == 302, response.content.decode()[:1500]


@pytest.mark.django_db
def test_contract_saved_from_the_client_page(staff_client, company):
    save_page(staff_client, company, {'price': '3000', 'contract_start': '2026-10-01', 'renewal_date': '2027-09-30',
                                      'billing_contact_name': 'Pat Payer', 'billing_contact_email': 'pay@sunpath.com'})
    contract = Contract.objects.get(client=company)
    assert contract.price == Decimal('3000') and contract.renewal_date == date(2027, 9, 30)
    assert contract.price_text == '$3,000 / month'
    assert AccessEntry.objects.filter(action='contract_added', client_id=company.pk).exists()
    save_page(staff_client, company, {'price': '3500', 'renewal_date': '2027-09-30'}, existing=contract)
    contract.refresh_from_db()
    assert contract.price == Decimal('3500') and Contract.objects.count() == 1
    assert AccessEntry.objects.filter(action='contract_changed', client_id=company.pk).exists()


@pytest.mark.django_db
def test_leaving_the_tab_empty_saves_no_contract(staff_client, company):
    save_page(staff_client, company, {})
    assert not Contract.objects.exists()


@pytest.mark.django_db
def test_renewal_warning_inside_the_notice_period(company):
    today = date(2026, 10, 11)
    contract = Contract.objects.create(client=company, renewal_date=today + timedelta(days=20), notice_days=30)
    assert contract.days_to_renewal(today) == 20 and contract.renews_soon(today)
    contract.renewal_date = today + timedelta(days=90)
    assert not contract.renews_soon(today)


@pytest.mark.django_db
def test_renewals_within_counts_only_live_clients(company, other_company):
    soon = date.today() + timedelta(days=10)
    Contract.objects.create(client=company, renewal_date=soon)
    Contract.objects.create(client=other_company, renewal_date=soon)
    other_company.status, other_company.is_active = 'ended', False
    other_company.save()
    assert list(renewals_within(30).values_list('client__name', flat=True)) == [company.name]


@pytest.mark.django_db
def test_contract_shows_on_page_and_list(staff_client, company):
    Contract.objects.create(client=company, price=Decimal('3000'), renewal_date=date.today() + timedelta(days=5))
    page = staff_client.get(f'/civ-admin/clients/client/{company.pk}/change/').content.decode()
    assert '$3,000 / month' in page and 'within notice period' in page and 'Contract &amp; billing' in page
    assert 'Renews' in staff_client.get('/civ-admin/clients/client/').content.decode()

