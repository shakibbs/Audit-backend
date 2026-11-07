"""Owner, 2026-10-31: a staff password may not contain the person's email name or name."""
import pytest
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from apps.staff.models import StaffUser

pytestmark = pytest.mark.django_db


def test_own_email_name_or_name_is_refused():
    staff = StaffUser(email='qa.super.staff@complyiv.com', name='Dana Reyes')
    for weak in ('qa.super.staff1', 'QA-Super-Staff-2026', 'Dana2026Dana!x', 'reyes-blue-lamp'):
        with pytest.raises(ValidationError):
            validate_password(weak, staff)
    validate_password('blue-river-lamp-42', staff)  # fine


def test_client_and_insurer_people_too(admin_user):
    """Owner, 2026-11-07: the same rule for portal users."""
    with pytest.raises(ValidationError):
        validate_password(admin_user.email.split('@')[0] + '-blue-lamp-42', admin_user)
    validate_password('blue-river-lamp-42', admin_user)
