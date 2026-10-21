"""The monthly audit report as a PDF, from the same saved figures the portal shows (owner decisions 2026-10-21):
score and grade, the six factors and the Exposure, every finding with its severity and the client's decision (never
the note: PDFs get forwarded), the month's alerts, and what is not yet measured. The footer carries the fingerprint of
the figures; the file's own fingerprint is kept with the report and in the access log."""
import hashlib
import io
import json
from datetime import date, datetime, timedelta

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.alerts.models import Alert
from apps.findings.build import ranked
from apps.scoring.portal import FAMILIES, score_page
from apps.scoring.snapshots import latest

TEAL, LINE = colors.HexColor('#0e8a78'), colors.HexColor('#dde6e3')
DISCLAIMER = ('Comply iV measures and records. It operates no controls, sits in no call path and makes no compliance decisions. '
              'Findings are measurements, not legal advice. Comply iV is not a law firm.')
DECIDED = {'accepted': 'Accepted', 'declined': 'Declined', 'alternative': 'Other plan'}


def figures(client, period: date) -> dict:
    """Everything the report shows, as plain data (also what its fingerprint covers)."""
    key = period.strftime('%Y-%m')
    score = score_page(client, key)
    run = latest(client, period)
    end = (period.replace(day=28) + timedelta(days=4)).replace(day=1)
    return {
        'client': client.name, 'period': period.strftime('%B %Y'),
        'score': score.get('score'), 'grade': score.get('grade'), 'partial': score.get('partial'),
        'families': score.get('families', []), 'caps': score.get('caps', []),
        'factors': [{'key': f['key'], 'name': f.get('name', ''), 'value': f['value']} for f in (run.score.get('factors', []) if run else [])],
        'defect': run.score.get('defect') if run else None, 'exposure': (run.score.get('exposure') or {}) if run else {},
        'findings': [{'severity': f.severity, 'title': f.title, 'why': f.why, 'domain': f.domain,
                      'status': 'Resolved' if f.status == 'resolved' else 'Open', 'decision': DECIDED.get(f.decision, 'No decision yet')}
                     for f in ranked(client)],
        'alerts': [{'severity': a.severity, 'title': a.title, 'at': a.first_at.date().isoformat(), 'reviewed': a.reviewed}
                   for a in Alert.objects.filter(client=client, first_at__date__gte=period, first_at__date__lt=end).order_by('first_at')],
        'notMeasured': sorted(m.code for m in run.metrics.all() if m.state in ('not_measured', 'rule_pending')) if run else [],
        'revised': bool(run and run.revised),
    }


def text_of(data: dict) -> str:
    """Every word the report prints, for the banned-word check."""
    return json.dumps(data, ensure_ascii=False) + ' ' + DISCLAIMER


def table(rows, widths):
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), TEAL), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white), ('FONTSIZE', (0, 0), (-1, -1), 8),
                           ('GRID', (0, 0), (-1, -1), 0.25, LINE), ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    return t


def render(data: dict, content_sha: str) -> bytes:
    out = io.BytesIO()
    styles = getSampleStyleSheet()
    body, small = styles['BodyText'], styles['BodyText'].clone('small', fontSize=8, leading=10)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 6.5)
        canvas.drawString(36, 22, f'Figures fingerprint (SHA-256): {content_sha} · page {doc.page}')
        canvas.restoreState()

    doc = SimpleDocTemplate(out, pagesize=letter, title=f'Audit report {data["period"]}', leftMargin=36, rightMargin=36, bottomMargin=40)
    e = data['exposure']
    parts = [Paragraph(f'Audit report · {data["client"]}', styles['Title']),
             Paragraph(f'{data["period"]}' + (' · revised after late records or a rule change' if data['revised'] else ''), body), Spacer(1, 8)]
    if data['score'] is None:
        parts.append(Paragraph('Not measured yet: no saved scores for this month.', body))
    else:
        partial = data['partial']
        parts.append(Paragraph(f'<b>Audit Score {data["score"]:.1f} · grade {data["grade"]}</b>'
                               + (f' · partial: {partial["factorsMeasured"]} of {partial["factors"]} factors measured' if partial else '')
                               + ' · draft bands', body))
        if e.get('value') is not None:
            parts.append(Paragraph(f'Exposure {e["value"]} · grade {e["grade"]} (D {data["defect"]} × venue {e["venue"]["value"]} × '
                                   f'targeting {e["targeting"]["value"]} × volume {e["volume"]["value"]})', body))
        parts += [Spacer(1, 6), table([['Family', 'Score']] + [[f['family'], '-' if f['score'] is None else f'{f["score"]:.1f}'] for f in data['families']], [300, 80])]
        if data['factors']:
            parts += [Spacer(1, 6), table([['Factor', 'Value (higher = more exposed)']]
                                          + [[f'{f["key"]} {f["name"]}', 'Pending' if f['value'] is None else f'{f["value"]:.1f}'] for f in data['factors']], [300, 160])]
        parts += [Spacer(1, 6), table([['Cap', 'State']] + [[c['name'], Paragraph(('Holding. ' if c['held'] else '') + c['detail'], small)] for c in data['caps']], [140, 400])]
    parts += [Spacer(1, 10), Paragraph('<b>Findings</b>', body)]
    if data['findings']:
        parts.append(table([['Severity', 'Finding', 'Domain', 'Status', 'Decision']]
                           + [[f['severity'], Paragraph(f'{f["title"]}. {f["why"]}', small), f['domain'], f['status'], f['decision']] for f in data['findings']],
                           [50, 290, 45, 55, 100]))
    else:
        parts.append(Paragraph('None.', body))
    parts += [Spacer(1, 10), Paragraph('<b>Alerts raised this month</b>', body)]
    parts.append(table([['Date', 'Severity', 'Alert', 'Reviewed']] + [[a['at'], a['severity'], Paragraph(a['title'], small), 'Yes' if a['reviewed'] else 'No']
                                                                        for a in data['alerts']], [60, 50, 340, 60]) if data['alerts'] else Paragraph('None.', body))
    parts += [Spacer(1, 10), Paragraph('<b>Not yet measured</b>', body),
              Paragraph(', '.join(data['notMeasured']) or 'Nothing.', small), Spacer(1, 14), Paragraph(DISCLAIMER, small)]
    doc.build(parts, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()


def build(data: dict) -> tuple[bytes, str]:
    content_sha = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
    return render(data, content_sha), content_sha


def period_of(key: str) -> date:
    return datetime.strptime(key, '%Y-%m').date()
