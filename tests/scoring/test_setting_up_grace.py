"""Owner, 2026-11-16 (option B3): in a client's first 30 days a missing internal do-not-call list or reassigned-number
log is "not measured"; after that it counts as the worst case."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.contacts.models import ContactEvent
from apps.scoring.extra import internal_list, reassigned_checks

pytestmark = pytest.mark.django_db


def test_first_30_days_then_worst_case(company):
    contacts = ContactEvent.objects.filter(client=company)
    company.start_date = timezone.localdate() - timedelta(days=5)
    early = internal_list(company, contacts)
    assert early['value'] is None and 'worstCase' not in early and 'not uploaded yet' in early['notMeasured']
    assert 'worstCase' not in reassigned_checks(company, contacts)
    company.start_date = timezone.localdate() - timedelta(days=31)
    late = internal_list(company, contacts)
    assert late['worstCase'] is True and late['display'] == 'Worst case'
    assert reassigned_checks(company, contacts)['worstCase'] is True
