"""Business days as the Rulebook counts them (business_day_calendar): Mon–Fri except US federal holidays,
on the recipient's own calendar date. Used for opt-out deadlines and "added to the list in time" checks."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from .lookup import RuleSet

WEEKDAYS = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th weekday of the month (n = -1 for the last)."""
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    last = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    """A holiday on Saturday is observed on Friday, on Sunday on Monday."""
    return day - timedelta(days=1) if day.weekday() == 5 else day + timedelta(days=1) if day.weekday() == 6 else day


def named_holidays(year: int) -> list[tuple[date, str, date]]:
    """(observed date, name, actual date) of US federal holidays observed in this year (5 U.S.C. 6103)."""
    days = [(date(year, 1, 1), "New Year's Day"), (_nth_weekday(year, 1, 0, 3), 'Martin Luther King Jr. Day'),
            (_nth_weekday(year, 2, 0, 3), "Washington's Birthday"), (_nth_weekday(year, 5, 0, -1), 'Memorial Day'),
            (date(year, 7, 4), 'Independence Day'), (_nth_weekday(year, 9, 0, 1), 'Labor Day'),
            (_nth_weekday(year, 10, 0, 2), 'Columbus Day'), (date(year, 11, 11), 'Veterans Day'),
            (_nth_weekday(year, 11, 3, 4), 'Thanksgiving Day'), (date(year, 12, 25), 'Christmas Day'),
            (date(year + 1, 1, 1), "New Year's Day")]  # next New Year may be observed on Dec 31
    if year >= 2021:
        days.append((date(year, 6, 19), 'Juneteenth'))  # a federal holiday since 2021
    return sorted((_observed(d), name, d) for d, name in days if _observed(d).year == year)


@lru_cache(maxsize=64)
def us_federal_holidays(year: int) -> frozenset[date]:
    return frozenset(observed for observed, _, _ in named_holidays(year))


def pick_time_zone(zip_tz: str | None, area_code_tz: str | None, fallback: list[str]) -> str:
    """Recipient time zone by the Rulebook's order (business_day_tz_fallback): ZIP, then area code, then the default."""
    found = {'recipient_zip': zip_tz, 'area_code': area_code_tz}
    return next(found.get(step) or step for step in fallback if found.get(step) or '/' in step)


def local_date(moment: datetime, time_zone: str) -> date:
    """The recipient's calendar date for a moment: 23:30 Friday in Los Angeles is Friday, not Saturday."""
    return moment.astimezone(ZoneInfo(time_zone)).date()


class BusinessCalendar:
    """The Rulebook's business-day calendar in force on a date."""

    def __init__(self, rules: RuleSet | None = None, on: date | None = None):
        rules = rules or RuleSet()
        found = rules.get('business_day_calendar', on=on or date.today())
        self.rule = found
        calendar = found.require()
        self.weekdays = {WEEKDAYS[d] for d in calendar['weekdays']}
        self.skip_federal_holidays = calendar.get('except') == 'us_federal_holidays'

    def is_business_day(self, day: date) -> bool:
        return day.weekday() in self.weekdays and not (self.skip_federal_holidays and day in us_federal_holidays(day.year))

    def add(self, start: date, n: int) -> date:
        """The n-th business day after `start`; `start` itself never counts (a STOP on Friday: Monday is day 1)."""
        day = start
        for _ in range(n):
            day += timedelta(days=1)
            while not self.is_business_day(day):
                day += timedelta(days=1)
        return day

    def between(self, start: date, end: date) -> int:
        """Business days after `start` up to and including `end` (0 when end is not after start)."""
        return sum(1 for i in range(1, (end - start).days + 1) if self.is_business_day(start + timedelta(days=i)))


@dataclass(frozen=True)
class Deadline:
    date: date  # last day to finish stopping, on the recipient's calendar
    business_days: int
    time_zone: str
    provisional: bool  # the deadline or the calendar is still Proposed: say so wherever it is shown


def optout_deadline(received_at: datetime, *, time_zone: str, rules: RuleSet | None = None) -> Deadline:
    """When must every system have stopped contacting someone who opted out at `received_at`?"""
    rules = rules or RuleSet()
    start = local_date(received_at, time_zone)
    days = rules.get('optout_deadline_business_days', on=start)
    calendar = BusinessCalendar(rules, start)
    n = days.require()
    return Deadline(calendar.add(start, n), n, time_zone, days.provisional or calendar.rule.provisional)
