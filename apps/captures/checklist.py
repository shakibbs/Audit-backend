"""The consent checklist (spec Lead Inspector check 3): rule-based items read from CiV's own page capture. Items that
need meaning (stop anytime, not a condition of purchase, autodialer disclosed) wait for AI: never measured here.

Owner decisions 2026-10-21: a phone box and a button but no consent words = no consent text; no phone box = not
measured (the form may go on in later steps). Phone and computer size: the worse counts. Minimum text size 10 px
(draft). The company named: the client's own name, information only (no brand list).
"""
import re

PASS, FAIL, NOT_MEASURED = 'pass', 'fail', 'not_measured'
WORDING = ['CC_BUTTON_MATCH', 'CC_NUMBER_SHOWN', 'CC_FONT_SIZE', 'CC_CONTRAST']  # fail → weak (wording)
WARNINGS = ['CC_ABOVE_BUTTON', 'CC_NO_SCROLL']  # fail → warning only
INFO = ['CC_SELLER_NAMED']  # information only (seller_named_required is false)
AI_ITEMS = ['CC_OPT_OUT', 'CC_NOT_CONDITION', 'CC_AUTODIAL_DISCLOSED']  # meaning: AI modules
ORDER = ['CC_CONSENT_TEXT', 'CC_UNTICKED', *WORDING, *WARNINGS, *INFO]
RANK = {PASS: 0, NOT_MEASURED: 1, FAIL: 2}
NEAR_PX = 250  # a checkbox this close to the consent words belongs to them
LARGE_PX = 24  # large text needs less contrast
CLICK = re.compile(r'by (?:clicking|pressing|tapping|selecting|submitting)\s+(?:on\s+)?(?:the\s+)?["“”\'‘’]?([^"“”\'‘’,.]{2,40}?)["“”\'‘’]?(?:\s+button)?[,\s]', re.I)
NUMBER = re.compile(r'(number|phone)\s+(?:i\s+|you\s+)?(?:have\s+)?(?:provided|entered|given|above|below|listed)|at the (?:number|phone)|this (?:number|phone)|(?:telephone|phone|mobile|cell) number', re.I)
NAME_NOISE = {'inc', 'llc', 'ltd', 'co', 'corp', 'corporation', 'company', 'the', 'of', 'and'}


def _norm(text: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', ' ', text.lower())).strip()


def _rgb(colour: str) -> tuple[float, float, float] | None:
    found = re.findall(r'[\d.]+', colour or '')
    return tuple(float(x) for x in found[:3]) if len(found) >= 3 else None


def contrast(fore: str, back: str) -> float | None:
    def light(rgb):
        c = [v / 255 for v in rgb]
        c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    f, b = _rgb(fore), _rgb(back)
    if not f or not b:
        return None
    hi, lo = sorted((light(f), light(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def one_viewport(m: dict, client_name: str, min_font: float, min_contrast: dict) -> dict:
    """Each item for one screen size: pass / fail / not_measured."""
    block = m.get('consentBlock')
    has_form = bool(m.get('phoneFields')) and bool(m.get('buttons'))
    if not block:
        if has_form:  # the real form, with nothing asking for permission
            return {'CC_CONSENT_TEXT': FAIL, **{k: NOT_MEASURED for k in ORDER[1:]}}
        return {k: NOT_MEASURED for k in ORDER}  # consent text not on this page (a later step of the form)
    text = block.get('text', '')
    items = {'CC_CONSENT_TEXT': PASS}
    near = [c for c in m.get('checkboxes', []) if c.get('visible', True)
            and abs((c.get('top') or 0) - (block.get('top') or 0)) <= NEAR_PX + (block.get('height') or 0)]
    items['CC_UNTICKED'] = FAIL if any(c.get('checked') for c in near) else PASS
    clicked = CLICK.search(text + ' ')
    buttons = [_norm(b.get('text', '')) for b in m.get('buttons', []) if b.get('text')]
    if clicked:
        said = _norm(clicked.group(1))
        items['CC_BUTTON_MATCH'] = PASS if any(said == b or said in b or b in said for b in buttons if b) else FAIL
    else:
        items['CC_BUTTON_MATCH'] = NOT_MEASURED  # the words do not name a button (e.g. a checkbox consent)
    items['CC_NUMBER_SHOWN'] = PASS if NUMBER.search(text) else FAIL
    size = block.get('fontSize')
    items['CC_FONT_SIZE'] = NOT_MEASURED if size is None else PASS if size >= min_font else FAIL
    ratio = contrast(block.get('color', ''), block.get('background', ''))
    need = min_contrast.get('large' if (size or 0) >= LARGE_PX else 'normal', 4.5)
    items['CC_CONTRAST'] = NOT_MEASURED if ratio is None else PASS if ratio >= need - 0.005 else FAIL
    submit = [b for b in m.get('buttons', []) if b.get('text')]
    if submit:
        bottom = max(b.get('top', 0) for b in submit)
        items['CC_ABOVE_BUTTON'] = PASS if (block.get('top') or 0) < bottom else FAIL
    else:
        items['CC_ABOVE_BUTTON'] = NOT_MEASURED
    view = (m.get('viewport') or {}).get('height')
    items['CC_NO_SCROLL'] = NOT_MEASURED if not view else PASS if (block.get('top') or 0) < view else FAIL
    words = [w for w in _norm(client_name).split() if w not in NAME_NOISE]
    items['CC_SELLER_NAMED'] = NOT_MEASURED if not words else PASS if ' '.join(words) in _norm(text) else FAIL
    return items


def evaluate(by_viewport: dict[str, dict], client_name: str, min_font: float = 10, min_contrast: dict | None = None) -> dict:
    """All screen sizes together: each item takes the worse answer. Returns items, the codes they cause, warnings."""
    min_contrast = min_contrast or {'normal': 4.5, 'large': 3.0}
    views = {v: one_viewport(m, client_name, min_font, min_contrast) for v, m in by_viewport.items()}
    items = {k: max((vals[k] for vals in views.values()), key=RANK.get, default=NOT_MEASURED) for k in ORDER}
    items.update({k: NOT_MEASURED for k in AI_ITEMS})
    codes = []
    if items['CC_CONSENT_TEXT'] == FAIL:
        codes.append('NP_NO_CONSENT_TEXT')
    if items['CC_UNTICKED'] == FAIL:
        codes.append('NP_PRETICKED')
    if any(items[k] == FAIL for k in WORDING):
        codes.append('WK_WORDING')
    return {'items': items, 'codes': codes, 'warnings': [k for k in WARNINGS if items[k] == FAIL],
            'measured': items['CC_CONSENT_TEXT'] != NOT_MEASURED, 'by_viewport': views}


def for_certificate(claim, consent_at, client_name: str, gap_days: float = 1, min_font: float = 10, min_contrast: dict | None = None):
    """The checklist from CiV's capture of the certificate's page closest to the consent time, if one was taken within
    `gap_days` (page_snapshot_max_gap_days). None = no capture close enough: not measured."""
    from datetime import timedelta

    from .models import PageCapture
    if not claim.page or consent_at is None:
        return None
    near = (PageCapture.objects.filter(client_id=claim.client_id, page__address=claim.page, ok=True,
                                       captured_at__gte=consent_at - timedelta(days=gap_days), captured_at__lte=consent_at + timedelta(days=gap_days))
            .only('captured_at', 'viewport', 'measurements'))
    shots = list(near)
    if not shots:
        return None
    when = min({s.captured_at for s in shots}, key=lambda t: abs(t - consent_at))
    found = evaluate({s.viewport: s.measurements for s in shots if s.captured_at == when}, client_name, min_font, min_contrast)
    found['captured_at'] = when
    return found
