"""Owner, 2026-10-30: the Alerts page follows the month picker — alerts open at some point in that month."""
from datetime import UTC, datetime

import pytest

from apps.alerts.models import Alert

pytestmark = pytest.mark.django_db


def alert(company, key, first, resolved=None):
    return Alert.objects.create(client=company, key=key, kind='Source stale', severity='Medium', title=key, detail='d', domain='DAT',
                                first_at=first, at=first, resolved_at=resolved)


def test_alerts_by_month(company, member_user, signed_in):
    alert(company, 'august-only', datetime(2026, 8, 3, tzinfo=UTC), resolved=datetime(2026, 8, 9, tzinfo=UTC))
    alert(company, 'aug-to-now', datetime(2026, 8, 20, tzinfo=UTC))
    alert(company, 'october', datetime(2026, 10, 2, tzinfo=UTC))
    api = signed_in(member_user)
    titles = lambda q: sorted(a['title'] for a in api.get(f'/api/alerts{q}').json())  # noqa: E731
    assert titles('?period=2026-08') == ['aug-to-now', 'august-only']
    assert titles('?period=2026-09') == ['aug-to-now']
    assert titles('?period=2026-10') == ['aug-to-now', 'october']
    assert len(titles('')) == 3  # no month (the sidebar count): every alert
