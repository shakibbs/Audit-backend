"""Owner, 2026-10-31: the Client reports list says "None found" instead of "None", and shows banned words in red."""
from datetime import date

import pytest

from apps.reports.models import Report
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_banned_words_column_in_plain_words(client, company):
    Report.objects.create(client=company, name='Period audit report', period=date(2026, 9, 1), status='ready', made_by='CiV')
    Report.objects.create(client=company, name='Period audit report', period=date(2026, 8, 1), status='blocked', made_by='CiV',
                          banned=['violation'])
    client.force_login(StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD))
    page = client.get('/civ-admin/reports/report/').content.decode()
    assert 'None found' in page and 'pill-red">violation<' in page and '>None<' not in page
