"""Bug fix 2026-10-23: every Rulebook "History" link opened an error page (name clash with Django's own history)."""
import re

import pytest

from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.rulebook.models import RuleValue
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(client):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    return client


def test_history_opens_from_the_list_the_check_page_and_the_rule_page(staff):
    links = set()
    for page in ('/civ-admin/rulebook/rulevalue/', '/civ-admin/rulebook/rulevalue/check/'):
        html = staff.get(page).content.decode()
        links |= set(re.findall(r'href="(/civ-admin/rulebook/rulevalue/rule-history/[^"]+)"', html))
    assert len(links) > 20
    for link in sorted(links)[:25]:
        assert staff.get(link).status_code == 200, link
    rule = RuleValue.objects.filter(key='calling_hours').first()
    button = staff.get(f'/civ-admin/rulebook/rulevalue/{rule.pk}/history/')
    assert button.status_code == 302 and button['Location'].endswith('/rule-history/calling_hours/')
    assert 'calling_hours' in staff.get(button['Location']).content.decode()
