"""Owner, 2026-10-31: Convoso and Five9 give local time; the November hour that happens twice and the March hour that
never happens are read carefully, every other time as before."""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apps.sync.localtime import LocalTimes, NEVER, TWICE, to_utc

NY = ZoneInfo('America/New_York')


def test_an_ordinary_time_is_read_as_before():
    assert to_utc(datetime(2026, 10, 30, 14, 5), NY) == (datetime(2026, 10, 30, 18, 5, tzinfo=UTC), '')


def test_the_doubled_hour_says_it_could_be_an_hour_later():
    utc, note = to_utc(datetime(2026, 11, 1, 1, 30), NY)
    assert utc == datetime(2026, 11, 1, 5, 30, tzinfo=UTC) and note == TWICE


def test_the_order_of_the_calls_picks_the_second_one():
    class Tool(LocalTimes):
        tz = NY
    tool = Tool()
    rows = [{'id': 1, 'at': datetime(2026, 11, 1, 1, 50)}, {'id': 2, 'at': datetime(2026, 11, 1, 1, 10)}]
    tool.remember(rows, lambda r: r['at'])
    first, second = (tool.reading(r, r['at']) for r in rows)
    assert first == (datetime(2026, 11, 1, 5, 50, tzinfo=UTC), TWICE)
    assert second[0] == datetime(2026, 11, 1, 6, 10, tzinfo=UTC) and 'second 1:10 am' in second[1]


def test_the_missing_march_hour_moves_forward():
    utc, note = to_utc(datetime(2027, 3, 14, 2, 30), NY)
    assert utc.astimezone(NY).hour == 3 and note == NEVER.format(t='2:30 am', moved='3:30 am')
