"""Calling window for a person: allowed hours in their own time, from the Rulebook (draft values while TBD, said so),
checked in every possible time zone. Advice only: CiV does not block calls."""
from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.rulebook.lookup import NoRulebook, RuleSet


def _hours(value: dict) -> str:
    def h(t: str) -> str:
        hour, minute = (int(x) for x in t.split(':'))
        return f'{hour % 12 or 12}{":" + str(minute).zfill(2) if minute else ""}{"am" if hour < 12 else "pm"}'
    text = f"{h(value['start'])} – {h(value['end'])}"
    return text + (f"; Sunday from {h(value['sunday_start'])}" if value.get('sunday_start') else '')


def _allowed(local: datetime, value: dict) -> bool:
    start = value['sunday_start'] if local.weekday() == 6 and value.get('sunday_start') else value['start']
    now = local.strftime('%H:%M')
    return start <= now < value['end']


def window(state: str, zones: list[str], is_non_us: bool, at: datetime | None = None) -> dict:
    """{'verdict': ok | not_safe | unknown, 'hours', 'status', 'draft', 'zones': [{zone, localTime, allowed}], 'note', 'holidays'}."""
    at = at or timezone.now()
    out = {'verdict': 'unknown', 'hours': None, 'status': None, 'draft': False, 'zones': [], 'note': '',
           'holidays': 'State holiday restrictions: not set yet (counsel item A8)'}
    if is_non_us:
        out['note'] = 'Outside the United States: US calling-hour rules do not cover this number. CiV flags it for review.'
        return out
    if not zones:
        out['note'] = 'Where this person is cannot be told from the number.'
        return out
    try:
        rule = RuleSet('draft').get('calling_hours', on=at.date(), state=state or None)
    except NoRulebook:
        out['note'] = 'No rulebook loaded.'
        return out
    value = rule.value
    out.update(hours=_hours(value) if value else None, status=rule.status, draft=rule.status == 'tbd',
               place='Federal' if rule.jurisdiction == 'US' else rule.jurisdiction)
    if not value:
        out['note'] = 'Calling hours not set yet.'
        return out
    for zone in zones:
        local = at.astimezone(ZoneInfo(zone))
        out['zones'].append({'zone': zone, 'localTime': local.strftime('%a %-I:%M %p'), 'allowed': _allowed(local, value)})
    out['verdict'] = 'ok' if all(z['allowed'] for z in out['zones']) else 'not_safe'
    if len(zones) > 1:
        out['note'] = 'The number could be in more than one time zone: the stricter one decides.'
    if out['draft']:
        out['note'] = (out['note'] + ' ' if out['note'] else '') + 'Draft hours: not confirmed by a lawyer yet.'
    return out
