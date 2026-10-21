"""Rulebook snapshot (Reports & Exports): every rule value in force on the last day of a month, with its status,
owner and effective date, as a PDF."""
import io
from datetime import date, timedelta

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .lookup import RuleSet


def month_end(period: str) -> date:
    first = date.fromisoformat(f'{period}-01')
    return (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def rows_in_force(on: date) -> tuple[str, list[list[str]]]:
    rules = RuleSet()
    out = []
    for key, rows in sorted(rules._by_key.items()):
        for r in rows:
            if (r.effective_from is None or r.effective_from <= on) and (r.effective_to is None or on <= r.effective_to):
                out.append([key, r.jurisdiction, r.shown[:80], r.get_status_display(), r.owner, r.effective_from.isoformat() if r.effective_from else 'before the lookback'])
    return f'v{rules.version.version} ({rules.version.status})', out


def snapshot_pdf(client_name: str, period: str) -> bytes:
    on = month_end(period)
    version, rows = rows_in_force(on)
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=landscape(letter), title=f'Rulebook snapshot {period}', leftMargin=36, rightMargin=36)
    styles = getSampleStyleSheet()
    small = styles['BodyText'].clone('small', fontSize=7.5, leading=9)
    table = Table([['Rule', 'Place', 'Value in force', 'Status', 'Owner', 'In force since'], *[[Paragraph(c, small) for c in r] for r in rows]],
                  colWidths=[150, 50, 270, 60, 70, 90], repeatRows=1)
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0e8a78')), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                               ('FONTSIZE', (0, 0), (-1, 0), 8), ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#dde6e3')),
                               ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    doc.build([Paragraph(f'Rulebook snapshot · {client_name}', styles['Title']),
               Paragraph(f'Rules in force on {on:%d %B %Y} · Rulebook {version} · {len(rows)} values. '
                         'Proposed and TBD values are not yet confirmed by a lawyer.', styles['BodyText']),
               Spacer(1, 10), table])
    return out.getvalue()
