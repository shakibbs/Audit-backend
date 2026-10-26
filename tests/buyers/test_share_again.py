"""Super test 2026-10-23: sharing with an insurer CiV already knows says what happened and never silently drops what
the Admin typed (company name, insurer or acquirer, end date, the person's name)."""
from datetime import date

import pytest

from apps.buyers.models import BuyerInvite, BuyerLink
from tests.buyers.test_sharing import share

pytestmark = pytest.mark.django_db


def test_sharing_again_keeps_the_end_date_and_the_name_and_says_so(company, admin_user, signed_in):
    api = signed_in(admin_user)
    first = share(api).json()
    assert first['message'].startswith('Now sharing with Falcon Risk (insurer).') and 'invite' in first['message']
    again = api.call('post', '/api/buyer-links', {'name': 'Falcon Risk', 'email': 'j.merchant@falconrisk.com', 'endsOn': '2027-06-30'}).json()
    assert 'Already sharing with Falcon Risk. End date changed to 30 Jun 2027.' in again['message']
    assert BuyerLink.objects.get().ends_on == date(2027, 6, 30)
    assert BuyerInvite.objects.get(used_at__isnull=True).name == 'J. Merchant'  # not wiped by the second share


def test_a_different_company_name_or_kind_is_answered_not_ignored(company, admin_user, signed_in):
    api = signed_in(admin_user)
    share(api)
    other = share(api, email='a.lee@falconrisk.com', name='QA-SA Ins').json()
    assert 'belongs to Falcon Risk on CiV, so "QA-SA Ins" is not used' in other['message']
    wrong = share(api, email='a.lee@falconrisk.com', kind='acquirer', endsOn='2099-01-01')
    assert wrong.status_code == 400 and 'set up on CiV as an insurer, not an acquirer' in wrong.json()['detail']
