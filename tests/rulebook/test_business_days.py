"""Business days: Mon–Fri, US federal holidays skipped, counted on the recipient's own calendar."""
from datetime import UTC, date, datetime

import pytest

from apps.rulebook.business_days import BusinessCalendar, local_date, optout_deadline, pick_time_zone, us_federal_holidays
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.rulebook.lookup import RuleSet


@pytest.fixture
def calendar(db):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    return BusinessCalendar(RuleSet(), date(2026, 11, 1))


def test_stop_on_friday_before_thanksgiving(db):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    stop = datetime(2026, 11, 20, 20, 0, tzinfo=UTC)  # 3pm in Florida
    deadline = optout_deadline(stop, time_zone='America/New_York')
    assert deadline.date == date(2026, 12, 7) and deadline.business_days == 10
    assert deadline.provisional  # the 10 days are still Proposed (counsel item A1)


def test_weekends_and_holidays_are_skipped(calendar):
    assert not calendar.is_business_day(date(2026, 11, 21))  # Saturday
    assert not calendar.is_business_day(date(2026, 11, 26))  # Thanksgiving
    assert calendar.is_business_day(date(2026, 11, 27))  # the Friday after is a business day
    assert calendar.add(date(2026, 12, 24), 1) == date(2026, 12, 28)  # Christmas Friday, then the weekend


def test_holidays_on_weekends_are_skipped_on_the_observed_day():
    assert date(2026, 7, 3) in us_federal_holidays(2026)  # July 4 2026 is a Saturday
    assert date(2027, 12, 31) in us_federal_holidays(2027)  # New Year 2028 is a Saturday
    assert date(2022, 12, 26) in us_federal_holidays(2022)  # Christmas 2022 was a Sunday
    assert date(2020, 6, 19) not in us_federal_holidays(2020)  # Juneteenth only from 2021


@pytest.mark.parametrize('year', range(2022, 2029))
def test_eleven_holidays_every_year_of_the_lookback(year):
    holidays = us_federal_holidays(year)
    observed_new_year_next = date(year + 1, 1, 1).weekday() == 5  # then it is observed on Dec 31 of this year
    observed_new_year_now = date(year, 1, 1).weekday() == 5  # and this year's falls in the year before
    assert len(holidays) == 11 + observed_new_year_next - observed_new_year_now
    assert all(d.weekday() < 5 for d in holidays)


def test_the_recipients_own_date_counts():
    late_friday_in_la = datetime(2026, 11, 21, 7, 30, tzinfo=UTC)  # 23:30 Friday in Los Angeles, Saturday in New York
    assert local_date(late_friday_in_la, 'America/Los_Angeles') == date(2026, 11, 20)
    assert local_date(late_friday_in_la, 'America/New_York') == date(2026, 11, 21)


def test_unknown_location_falls_back_zip_then_area_code_then_new_york():
    order = ['recipient_zip', 'area_code', 'America/New_York']
    assert pick_time_zone('America/Chicago', 'America/Denver', order) == 'America/Chicago'
    assert pick_time_zone(None, 'America/Denver', order) == 'America/Denver'
    assert pick_time_zone(None, None, order) == 'America/New_York'


def test_counting_business_days_between_two_dates(calendar):
    assert calendar.between(date(2026, 11, 20), date(2026, 12, 7)) == 10
    assert calendar.between(date(2026, 11, 20), date(2026, 11, 20)) == 0
    assert calendar.between(date(2026, 11, 20), date(2026, 11, 22)) == 0  # only the weekend
