"""Owner, 2026-10-31: a new exam question's Turns box opens empty (a grey example as hint), never with "null"."""
import pytest

from apps.conversations.models import ExamCase
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_the_turns_box_opens_empty(client):
    client.force_login(StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD))
    page = client.get('/civ-admin/conversations/examcase/add/').content.decode()
    box = page[page.index('name="turns"'):]
    box = box[:box.index('</textarea>')]
    assert box.rstrip().endswith('>') or box.split('>', 1)[1].strip() == ''  # nothing typed in it
    assert 'null' not in box.split('>', 1)[1] and 'Please stop calling me.' in box  # the hint is a placeholder
    sent = client.post('/civ-admin/conversations/examcase/add/', {'channel': 'sms', 'expected': 'stop', 'moment': '', 'note': 't',
                                                                 'turns': '[{"who": "customer", "text": "stop texting me"}]'})
    assert sent.status_code in (200, 302)
