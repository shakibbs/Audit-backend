"""Reading ids and values from the portal safely (QA 2026-10-23)."""


def number(text) -> int | None:
    """'12' → 12. Only plain 0–9 digits and at most 12 of them: '²', Arabic digits or a huge number give None."""
    text = str(text)
    return int(text) if text.isascii() and text.isdigit() and len(text) <= 12 else None


def ref_number(ref: str, prefix: str) -> int | None:
    """'rep-12' with prefix 'rep-' → 12; anything else → None."""
    return number(ref[len(prefix):]) if isinstance(ref, str) and ref.startswith(prefix) else None


def yes(value) -> bool:
    """A tick from JSON: only true (or "true") counts, so "false" or "nope" never turns a switch on."""
    return value is True or (isinstance(value, str) and value.strip().lower() == 'true')


def text(value, limit: int) -> str:
    """A text box: spaces tidied, at most `limit` characters; a number or list sent instead becomes text."""
    return ' '.join(str(value or '').split())[:limit] if not isinstance(value, (list, dict)) else ''


def month(value) -> str | None:
    """'2026-09' → '2026-09'. A real month between 2000 and 2100 only: '2026-13', '9999-12' or '٢٠٢٦-٠١' give None."""
    import re
    value = str(value or '')
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}', value):
        return None
    year, mon = int(value[:4]), int(value[5:])
    return value if 2000 <= year <= 2100 and 1 <= mon <= 12 else None


def year(value, default: int) -> int | None:
    """'2026' → 2026 (2000–2100); empty → the default; anything else → None."""
    if value in (None, ''):
        return default
    found = number(value)
    return found if found is not None and 2000 <= found <= 2100 else None


def day(value):
    """'2026-09-04' → a date between 2000 and 2100, or None."""
    import re
    from datetime import date
    value = str(value or '')
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        return None
    try:
        found = date.fromisoformat(value)
    except ValueError:
        return None
    return found if 2000 <= found.year <= 2100 else None


def month_span(period: str | None):
    """'2026-09' → (1 Sep 2026, 1 Oct 2026) as dates; None for no month (owner, 2026-10-30: pages follow the picker)."""
    from datetime import date, timedelta
    period = month(period)
    if period is None:
        return None
    first = date(int(period[:4]), int(period[5:]), 1)
    return first, (first.replace(day=28) + timedelta(days=4)).replace(day=1)
