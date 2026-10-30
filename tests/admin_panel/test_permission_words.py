"""Owner, 2026-10-31: a staff member's permission ticks say "insurer", not "buyer"; the Access log says "IP address"."""
import pytest
from django.contrib.auth.models import Permission

from apps.access_log.models import AccessEntry

pytestmark = pytest.mark.django_db


def test_plain_words():
    names = set(Permission.objects.filter(content_type__app_label='buyers').values_list('name', flat=True))
    assert {'Can view insurer invite', 'Can change insurer person', 'Can view sharing with an insurer'} <= names
    assert not any('buyer' in n.lower() for n in names)
    assert AccessEntry._meta.get_field('ip_address').verbose_name == 'IP address'
