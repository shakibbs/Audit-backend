"""Records completeness for one client in the admin: a tile at the top of the client page (overall %, the tool with
the lowest share) that opens a page with every tool, how it was checked, both numbers and the %."""
from datetime import timedelta

from django.utils import timezone

from apps.connections.providers import PROVIDERS

from .models import PeriodIntegrity, Reconciliation

M37 = ('calls', 'texts', 'vendor_leads', 'crm_records')
HOW = {
    'bill': "Compared with the tool's bill: CiV saw everything the client paid for.",
    'tool_total': "Compared with the tool's own count: CiV read everything the tool has.",
    'volume': 'No bill or total: working days with records, and no sudden drop.',
    'none': 'Not checked.',
}


def tool_name(code: str) -> str:
    return PROVIDERS[code].name if code in PROVIDERS else code


def _pct(ratio) -> str:
    return f'{ratio * 100:.0f}%' if ratio is not None else ''


def completeness_tile(client, url: str = '') -> tuple:
    month = PeriodIntegrity.objects.filter(client=client).first()  # newest month first
    if month is None:
        return ('Records completeness', '-', 'not yet measured · first check the night after a tool connects', url)
    when = month.period.strftime('%B %Y')
    rows = Reconciliation.objects.filter(client=client, period=month.period, measure__in=M37)
    tools = len({r.source_system for r in rows if r.source_system})
    if month.completeness is None:
        return ('Records completeness', '-', f'not available · {tools} tools, none comparable yet · {when}', url)
    lowest = rows.filter(available=True, ratio__isnull=False).order_by('ratio').first()
    state = 'Incomplete' if month.incomplete else 'Complete'
    foot = f'{state} · {when} · {tools} tools checked' + (f' · lowest: {tool_name(lowest.source_system)} {lowest.get_measure_display().lower()}' if lowest else '')
    return ('Records completeness', f'{month.completeness * 100:.0f}%', foot, url)


def _line(row: Reconciliation) -> dict:
    tool = tool_name(row.source_system)
    if row.independent_total is None:
        numbers = ''
    elif row.method == Reconciliation.Method.VOLUME:
        numbers = f'{row.records or 0} of {row.independent_total} working days with records'
    elif row.method == Reconciliation.Method.BILL:
        numbers = f'CiV read {row.records or 0:,} of {row.independent_total:,} billed'
    else:
        numbers = f'CiV read {row.records or 0:,} of {row.independent_total:,} in {tool}'
    if not row.available:
        color, state = 'gray', 'Not available'
    elif row.flagged:
        color, state = 'red', 'Below floor'
    elif row.ratio is not None and row.ratio > 1:
        color, state = 'amber', 'Review'
    else:
        color, state = 'green', 'OK'
    return {'tool': tool, 'what': row.get_measure_display(), 'how': row.get_method_display(), 'how_long': HOW[row.method],
            'numbers': numbers, 'pct': _pct(row.ratio) if row.available else '', 'color': color, 'state': state, 'note': row.note}


def completeness_months(client) -> list[dict]:
    """This month and last month, newest first, each with one line per tool and measure and the other checks."""
    this = timezone.localdate().replace(day=1)
    periods = [this, (this - timedelta(days=1)).replace(day=1)]
    months = []
    for month in PeriodIntegrity.objects.filter(client=client, period__in=periods).order_by('-period'):
        rows = list(Reconciliation.objects.filter(client=client, period=month.period).order_by('source_system', 'measure'))
        others = []  # all tools together: they can flag the month but are not in the %
        for row in rows:
            if row.measure in ('days_present', 'stop_replies'):
                numbers = (f'{row.records or 0} of {row.independent_total or 0} working days with any records' if row.measure == 'days_present'
                           else f'{row.records or 0:,} STOP replies to {row.independent_total or 0:,} texts')
                others.append({'tool': 'All tools', 'what': 'Days with records' if row.measure == 'days_present' else 'STOP replies',
                               'how': 'Extra check (not in %)', 'how_long': 'Can flag the month, but is not part of the percentage.',
                               'numbers': numbers, 'pct': _pct(row.ratio) if row.measure == 'days_present' else '',
                               'color': 'red' if row.flagged else 'green', 'state': 'Flagged' if row.flagged else 'OK', 'note': row.note})
        overall = ('gray', 'Not available') if month.completeness is None else ('red', 'Incomplete') if month.incomplete else ('green', 'Complete')
        months.append({'period': month.period, 'pct': _pct(month.completeness), 'color': overall[0], 'state': overall[1], 'floor': _pct(month.floor),
                       'lines': [_line(r) for r in rows if r.measure in M37] + others, 'checked_at': month.computed_at})
    return months
