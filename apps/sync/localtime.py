"""Tools that give local time (Convoso, Five9): the one hour a year that happens twice (November) and the one that never
happens (March) are read carefully (owner, 2026-10-31). Every other time is read as before."""
from datetime import UTC, datetime

TWICE = 'Clock-change hour: could be 1 hour later'
TWICE_SECOND = 'Clock-change hour: the second {t} (worked out from the order of the calls)'
NEVER = 'Clock-change hour: {t} did not exist that night; read as {moved}'


def clock(moment: datetime) -> str:
    return moment.strftime('%-I:%M %p').lower()


def to_utc(naive: datetime, tz, after: datetime | None = None) -> tuple[datetime, str]:
    """(the time in UTC, a note or ''). `after`: the call before it in the tool's own order, when known."""
    first, second = naive.replace(tzinfo=tz, fold=0), naive.replace(tzinfo=tz, fold=1)
    utc = first.astimezone(UTC)
    if utc.astimezone(tz).replace(tzinfo=None) != naive:  # the clock jumped over this time
        return utc, NEVER.format(t=clock(naive), moved=clock(utc.astimezone(tz)))
    if first.utcoffset() == second.utcoffset():
        return utc, ''
    later = second.astimezone(UTC)
    if after is not None and utc < after <= later:  # the first reading would go back in time
        return later, TWICE_SECOND.format(t=clock(naive))
    return utc, TWICE


class LocalTimes:
    """Remembers each row's reading, worked out in the tool's own order so a call after 1:50 am that says 1:10 am is the
    second 1:10 am."""
    def remember(self, rows: list[dict], naive_of) -> None:
        times, last = getattr(self, '_times', {}), None
        for row in rows:
            try:
                utc, note = to_utc(naive_of(row), self.tz, last)
            except ValueError:
                continue
            times[self._key(row)] = (utc, note)
            last = utc if last is None else max(last, utc)
        self._times = times

    @staticmethod
    def _key(row: dict) -> tuple:
        return tuple(sorted((str(k), str(v)) for k, v in row.items()))

    def reading(self, row: dict, naive: datetime) -> tuple[datetime, str]:
        found = getattr(self, '_times', {}).get(self._key(row))
        return found if found else to_utc(naive, self.tz)
