"""Owner, 2026-10-30: the Action Queue follows the month picker — a month shows the findings open during it."""
from datetime import date, datetime, UTC

import pytest

from apps.findings.models import Finding

pytestmark = pytest.mark.django_db


def finding(company, key, first, last_period, resolved=None):
    return Finding.objects.create(client=company, key=key, metric=key, domain='REV', severity='High', title=key, why='w',
                                  period=last_period, first_seen=first, last_seen=first, resolved_at=resolved,
                                  status='resolved' if resolved else 'open')


def test_a_month_shows_what_was_open_in_it(company, admin_user, signed_in):
    finding(company, 'M10', datetime(2026, 8, 5, tzinfo=UTC), date(2026, 10, 1))  # Aug to now
    finding(company, 'M12', datetime(2026, 10, 2, tzinfo=UTC), date(2026, 10, 1))  # new in October
    finding(company, 'M14', datetime(2026, 7, 1, tzinfo=UTC), date(2026, 8, 1), resolved=datetime(2026, 8, 20, tzinfo=UTC))  # gone in Aug
    api = signed_in(admin_user)
    titles = lambda q: sorted(a['title'] for a in api.get(f'/api/actions{q}').json())  # noqa: E731
    assert titles('') == ['M10', 'M12', 'M14']  # no month: everything
    assert titles('?period=2026-09') == ['M10']
    assert titles('?period=2026-08') == ['M10', 'M14']
    assert titles('?period=2026-10') == ['M10', 'M12']
    assert titles('?period=bad') == ['M10', 'M12', 'M14']
