"""Module 10 step 5: the scores the portal shows, all from the same saved metric scores (owner decision 2026-10-21:
one engine). A domain's score is the mean of its metrics' scores; the Audit Score is the mean of the measured
domains (higher = better, grades from the Rulebook's grade_bands); the six factors, D and the Exposure (higher = worse)
come from steps 3–4. Labels: "partial" while factors are pending, "draft bands" while the bands are drafts."""
from datetime import date, datetime

from apps.rulebook.lookup import NoRulebook, RuleSet

from .models import SnapshotRun
from .snapshots import latest, months_back

# The portal's 25 domains: family and the metrics they show (same as the portal's domain register).
DOMAINS = {
    'CON': ('Permission', ['M01', 'M02', 'M03']), 'WEB': ('Permission', ['M04', 'M05', 'M28']), 'LPV': ('Permission', ['M06', 'M26', 'M27']),
    'VND': ('Permission', ['M07', 'M29', 'M30']), 'AFF': ('Permission', ['M06', 'M26']), 'RND': ('Who you contact', ['M11']),
    'IDN': ('Who you contact', ['M12']), 'NDN': ('Who you contact', ['M13']), 'SDN': ('Who you contact', ['M13']),
    'XBD': ('Who you contact', ['M15']), 'DLR': ('How you contact', ['M19', 'M31']), 'PRV': ('How you contact', ['M19', 'M20']),
    'SMS': ('How you contact', ['M10', 'M16']), 'CTF': ('How you contact', ['M16', 'M17', 'M18']), 'IDD': ('How you contact', ['M21']),
    'SHK': ('How you contact', ['M21']), 'VLT': ('How you contact', []), 'REV': ('Stopping', ['M08', 'M09', 'M10']),
    'REC': ('Records', ['M22a', 'M22b']), 'RET': ('Records', ['M23']), 'SEC': ('Records', []), 'GOV': ('Company controls', ['M25a']),
    'INC': ('Company controls', ['M24']), 'PLT': ('Company controls', []), 'MNA': ('Company controls', ['M25b']),
}
OUTSIDE = {'NDN', 'SDN'}  # shown, never in the overall (spec §9)
FAMILIES = ['Permission', 'Who you contact', 'How you contact', 'Stopping', 'Records', 'Company controls']
STOP_CAP = {'REV': 'M10', 'IDN': 'M12'}  # contact after a stop / an internal-list entry: that domain's grade at most D
DRAFT_GRADES = {'A': 90, 'B': 80, 'C': 70, 'D': 60}


def cutoffs(on: date) -> dict:
    try:
        return RuleSet().get('grade_bands', on=on).value or DRAFT_GRADES
    except (NoRulebook, KeyError, LookupError):
        return DRAFT_GRADES


def grade_of(x: float, bands: dict) -> str:
    return next((g for g in 'ABCD' if x >= bands[g]), 'F')


def run_for(client, key: str | None) -> SnapshotRun | None:
    if key:
        return latest(client, datetime.strptime(key, '%Y-%m').date())
    return SnapshotRun.objects.filter(client=client).order_by('-period', '-version').first()


class Fixed:
    """A metric as if its finding were fixed (Module 11 step 4): perfect score, nothing left to hold a domain down."""
    def __init__(self, code):
        self.code, self.score, self.value, self.state = code, 100.0, 0, 'measured'


def domain_scores(run: SnapshotRun, bands: dict, fixed: set[str] = frozenset()) -> dict:
    by = {m.code: (Fixed(m.code) if m.code in fixed else m) for m in run.metrics.all()}
    by.update({c: Fixed(c) for c in fixed if c not in by})
    out = {}
    for code, (family, codes) in DOMAINS.items():
        scored = [by[c] for c in codes if c in by and by[c].score is not None]
        if not scored:
            continue
        value = round(sum(m.score for m in scored) / len(scored), 1)
        held = code in STOP_CAP and STOP_CAP[code] in by and (by[STOP_CAP[code]].value or by[STOP_CAP[code]].state == 'worst_case')
        if held and value >= bands['C']:
            value = round(bands['C'] - 0.1, 1)  # grade D at best
        out[code] = {'code': code, 'family': family, 'score': value, 'total': len(codes), 'run': len(scored),
                     'pass': sum(m.score >= 90 for m in scored), 'warn': sum(60 <= m.score < 90 for m in scored),
                     'fail': sum(m.score < 60 for m in scored), 'notRun': len(codes) - len(scored), **({'held': True} if held else {})}
    return out


def overall(domains: dict) -> float | None:
    counted = [d['score'] for c, d in domains.items() if c not in OUTSIDE]
    return round(sum(counted) / len(counted), 1) if counted else None


def domains_page(client, key: str | None) -> list[dict]:
    run = run_for(client, key)
    if run is None:
        return []
    bands = cutoffs(run.period)
    now = domain_scores(run, bands)
    past = [domain_scores(r, bands) if r else {} for r in (latest(client, p) for p in months_back(run.period, 3))]
    return [{**d, 'history': [p.get(code, {}).get('score') for p in past] + [d['score']]} for code, d in now.items()]


def score_page(client, key: str | None) -> dict:
    run = run_for(client, key)
    if run is None:
        return {}
    bands = cutoffs(run.period)
    domains = domain_scores(run, bands)
    value = overall(domains)
    if value is None:
        return {}
    raw = grade_of(value, bands)
    exposure = run.score.get('exposure', {})
    hard = exposure.get('caps', {}).get('hard', {})
    cov = exposure.get('caps', {}).get('coverage', {})
    held_grade = 'C' if (hard.get('state') == 'held' or cov.get('state') == 'held') and raw in 'AB' else raw
    history = []
    for p in months_back(run.period, 3) + [run.period]:
        r = latest(client, p)
        v = overall(domain_scores(r, bands)) if r else None
        if v is not None:
            history.append({'period': p.strftime('%Y-%m'), 'label': p.strftime('%b'), 'score': v, 'grade': grade_of(v, bands), 'event': None})
    factors = run.score.get('factors', [])
    measured = sum(not f['pending'] for f in factors)
    stop_held = [d for d in domains.values() if d.get('held')]
    out = {
        'score': value, 'grade': held_grade, 'rawGrade': raw,
        'checkpointsRun': sum(d['run'] for d in domains.values()), 'checkpointsTotal': sum(len(c) for _, c in DOMAINS.values()),
        'domainsMeasured': len([c for c in domains if c not in OUTSIDE]), 'domainsTotal': len(DOMAINS),
        'families': [{'family': f, 'score': (lambda xs: round(sum(xs) / len(xs), 1) if xs else None)(
            [d['score'] for c, d in domains.items() if d['family'] == f and c not in OUTSIDE])} for f in FAMILIES],
        'history': history,
        'caps': [
            {'name': 'Hard cap', 'held': hard.get('state') == 'held',
             'detail': {'held': f"{100 * hard.get('share', 0):.1f}% of contacts that need proof have none or conflicting proof. Overall grade held at C.",
                        'clear': 'Contacts that need proof are within the limit.', 'rule_pending': 'Rule pending: the limit is not set yet (counsel).',
                        'not_measured': 'Not measured: no checked contacts that need proof.'}.get(hard.get('state'), 'Not measured.')},
            {'name': 'Contact-after-stop cap', 'held': bool(stop_held),
             'detail': ('Contact after a stop or a do-not-call entry: ' + ', '.join(d['code'] for d in stop_held) + ' held at D.') if stop_held
             else 'No contact after a stop or a do-not-call entry.'},
            {'name': 'Coverage cap', 'held': cov.get('state') == 'held',
             'detail': {'held': f"Evidence coverage is {100 * cov.get('value', 0):.0f}%, below the {100 * cov.get('floor', 0.6):.0f}% floor. Overall grade held at {cov.get('grade', 'C')}.",
                        'clear': f"Evidence coverage is {100 * cov.get('value', 0):.0f}%, above the {100 * cov.get('floor', 0.6):.0f}% floor."}.get(
                 cov.get('state'), 'Not measured: no score computed yet.')},
        ],
        'partial': {'factorsMeasured': measured, 'factors': len(factors)} if measured < len(factors) else None,
        'draftBands': True,
        'exposure': {'value': exposure.get('value'), 'grade': exposure.get('grade'), 'defect': run.score.get('defect')},
    }
    if run.score.get('coverage', {}).get('value') is not None:
        out['evidenceCoverage'] = run.score['coverage']['value']  # M36 (Module 14); before it, the portal keeps its sample
    if len(history) > 1:
        out['previous'] = history[-2]['score']
    out.update(projection(client, run, bands, value, hard))
    return out


TOP = 5  # owner decision 2026-10-21


def projection(client, run: SnapshotRun, bands: dict, today: float, hard: dict) -> dict:
    """The score if the top open findings were fixed (an estimate, not a measurement), and the hard-cap note."""
    from apps.findings.build import ranked
    top = [f for f in ranked(client) if f.status != 'resolved'][:TOP]
    out = {'cap': {'share': round(100 * hard['share'], 1), 'limit': None} if hard.get('state') == 'held' else None}
    if not top:
        return out
    fixed = {f.metric for f in top}
    value = overall(domain_scores(run, bands, fixed)) or today
    grade = grade_of(value, bands)
    clears = hard.get('state') == 'held' and 'M01' in fixed
    if hard.get('state') == 'held' and not clears and grade in 'AB':
        grade = 'C'  # still held by the hard cap
    out['projected'] = {'score': value, 'grade': grade, 'actions': len(top), 'clearsCap': clears}
    return out


def impact(client, metric: str) -> float | None:
    """How much the Audit Score would rise if this one finding were fixed."""
    run = run_for(client, None)
    if run is None:
        return None
    bands = cutoffs(run.period)
    now = overall(domain_scores(run, bands))
    after = overall(domain_scores(run, bands, {metric}))
    return round(after - now, 1) if now is not None and after is not None else None


def exposure_reading(client) -> dict | None:
    """The client's own Exposure reading in the shape the factor map and insurer pages use; pending factors are null."""
    run = SnapshotRun.objects.filter(client=client).order_by('-period', '-version').first()
    if run is None or not run.score.get('factors'):
        return None
    e = run.score.get('exposure', {})
    return {'factors': [f['value'] for f in run.score['factors']], 'venue': e.get('venue', {}).get('value', 1.0),
            'targeting': e.get('targeting', {}).get('value', 1.0), 'volume': e.get('volume', {}).get('value', 1.0),
            'source': f'Measured from records · {run.period:%b %Y}' + (' · partial' if run.score.get('partial') else '') + ' · draft bands'}
