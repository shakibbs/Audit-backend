"""Owner, 2026-10-31: a rule's page shows its value in plain words ("Mon–Fri except US federal holidays", "Not set yet"), never computer code."""
import pytest

from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.rulebook.models import RuleValue
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_a_rule_page_shows_plain_words(client):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    client.force_login(StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD))
    hours = RuleValue.objects.get(key='business_day_calendar', jurisdiction='US')  # stored as {'except': ..., 'weekdays': [...]}
    empty = RuleValue.objects.filter(value__isnull=True).first()
    page = client.get(f'/civ-admin/rulebook/rulevalue/{hours.pk}/change/').content.decode()
    assert '&#x27;weekdays&#x27;' not in page and "'weekdays'" not in page and 'Mon–Fri except US federal holidays' in page
    assert 'Not set yet' in client.get(f'/civ-admin/rulebook/rulevalue/{empty.pk}/change/').content.decode()


def test_places_have_plain_names(client):
    from apps.rulebook.health import place
    assert (place('US'), place('FL'), place('5th_circuit')) == ('Federal', 'Florida (FL)', '5th Circuit court')
    load(RULEBOOK_DIR / 'v3.0.yaml')
    client.force_login(StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD))
    page = client.get('/civ-admin/rulebook/rulevalue/').content.decode()
    assert '5th Circuit court' in page and '>5th_circuit<' not in page and 'Florida (FL)' in page
