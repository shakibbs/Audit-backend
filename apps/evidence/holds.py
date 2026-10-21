"""Module 14 step 4: legal holds. `Holds` answers one question for every 4-year deletion job: is this file under an
active hold of its company (its date, a number it holds, the vendor it belongs to)?"""
import re
from datetime import date, datetime

from apps.contacts.normalize import codes_for, mask
from apps.keyring.phones import normalize

from .models import LegalHold

DATE = re.compile(r'(\d{4}-\d{2}-\d{2})|(\d{1,2}/\d{1,2}/\d{4})')


class Holds:
    """The active holds of every company, read once per deletion run."""
    def __init__(self):
        from apps.tenancy.scope import all_clients
        with all_clients():
            self.rows = list(LegalHold.objects.filter(released_at__isnull=True))

    def covers(self, client_id: int, when=None, tokens=(), vendors=()) -> bool:
        day = when.date() if isinstance(when, datetime) else when
        for h in self.rows:
            if h.client_id != client_id:
                continue
            if h.scope == LegalHold.Scope.DATES and day and h.starts and h.ends and h.starts <= day <= h.ends:
                return True
            if h.scope == LegalHold.Scope.NUMBER and h.phone_token in set(tokens):
                return True
            if h.scope == LegalHold.Scope.VENDOR and h.vendor_key in set(vendors):
                return True
        return False


def parse_dates(text: str) -> tuple[date, date] | None:
    found = []
    for iso, us in DATE.findall(text or ''):
        try:
            found.append(date.fromisoformat(iso) if iso else datetime.strptime(us, '%m/%d/%Y').date())
        except ValueError:
            return None
    if len(found) != 2 or found[0] > found[1]:
        return None
    return found[0], found[1]


def place(client, scope: str, target: str, reason: str, by: str) -> LegalHold | str:
    """A new hold, or the reason it cannot be placed."""
    from apps.vendors.rates import vendor_key
    fields = {'client': client, 'scope': scope, 'reason': reason.strip()[:300], 'set_by': by}
    if scope == LegalHold.Scope.NUMBER:
        number = normalize(target)
        if number is None:
            return 'Enter the full phone number.'
        return LegalHold.objects.create(**fields, target=mask(number), phone_token=codes_for(client).token(number))
    if scope == LegalHold.Scope.VENDOR:
        if not target.strip():
            return 'Enter the vendor name.'
        return LegalHold.objects.create(**fields, target=' '.join(target.split())[:120], vendor_key=vendor_key(target))
    if scope == LegalHold.Scope.DATES:
        found = parse_dates(target)
        if found is None:
            return 'Enter two dates, e.g. 2026-01-01 to 2026-03-31.'
        return LegalHold.objects.create(**fields, target=f'{found[0]:%-d %b %Y} – {found[1]:%-d %b %Y}', starts=found[0], ends=found[1])
    return 'Choose what to hold.'


def number_held(client, token: str) -> bool:
    return LegalHold.objects.filter(client=client, scope=LegalHold.Scope.NUMBER, phone_token=token, released_at__isnull=True).exists()
