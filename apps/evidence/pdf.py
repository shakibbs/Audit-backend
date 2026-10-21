"""The evidence file as a PDF (the same data as the JSON). Its footer prints the fingerprint of the data it shows."""
import hashlib
import io
import json

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

TEAL, LINE = colors.HexColor('#0e8a78'), colors.HexColor('#dde6e3')


def data_sha(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def table(rows, widths):
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), TEAL), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white), ('FONTSIZE', (0, 0), (-1, -1), 7.5),
                           ('GRID', (0, 0), (-1, -1), 0.25, LINE), ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    return t


def render(data: dict) -> bytes:
    sha = data_sha(data)
    out = io.BytesIO()
    styles = getSampleStyleSheet()
    body, small = styles['BodyText'], styles['BodyText'].clone('small', fontSize=7.5, leading=9)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 6.5)
        canvas.drawString(36, 22, f'Evidence file data fingerprint (SHA-256): {sha} · page {doc.page}')
        canvas.restoreState()

    doc = SimpleDocTemplate(out, pagesize=landscape(letter), title=f'Evidence file {data["number"]}', leftMargin=30, rightMargin=30, bottomMargin=40)
    P = lambda t: Paragraph(str(t), small)  # noqa: E731
    parts = [Paragraph(f'Evidence file · {data["number"]} · {data["company"]}', styles['Title']), Paragraph(data['note'], body), Spacer(1, 6)]
    if data['owners']:
        parts += [Paragraph('<b>Owners of the number</b>', body),
                  table([['Owner', 'From', 'To', 'Why']] + [[o['number'], o['from'] or 'the start', o['to'] or 'now', o['reason']] for o in data['owners']],
                        [50, 160, 160, 350]), Spacer(1, 6)]
    parts += [Paragraph('<b>Contacts</b>', body),
              table([['When (UTC)', 'Channel', 'Result', 'Reason']] + [[P(c['occurredAt']), c['channel'], c['status'], P(c['code'])] for c in data['contacts']],
                    [170, 60, 90, 400]), Spacer(1, 6),
              Paragraph('<b>Proof elements</b>', body),
              table([['#', 'Element', 'Present', 'Tier', 'Source', 'Fingerprint']] + [[e['number'], P(e['element']),
                     '-' if e['present'] is None else ('Yes' if e['present'] else 'No'), e['tier'] or '-', P(e['source'] or '-'), P(e['hash'] or '-')]
                     for e in data['proofElements']], [20, 190, 50, 30, 120, 310]), Spacer(1, 6),
              Paragraph('<b>Fingerprints of what CiV saw</b>', body),
              table([['Record', 'Tool · ID', 'Fetched (UTC)', 'Fingerprint (SHA-256)', 'Sealed', 'Seal check', 'At the source now']] + [[
                     P(f['what']), P(f'{f["tool"]} · {f["record"]}'), P(f['fetchedAt']), P(f['sha256']), P(f['seal']['day'] if f['seal'] else '-'),
                     P(f['check']), P(f"{f['atSource']['result']} ({f['atSource']['checkedAt']:%d %b %Y})" if f.get('atSource') else 'Not asked again')]
                     for f in data['fingerprints']], [105, 130, 90, 180, 55, 80, 100]), Spacer(1, 10), Paragraph(data['disclaimer'], small)]
    doc.build(parts, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()
