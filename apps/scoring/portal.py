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


def domain_scores(run: SnapshotRun, bands: dict) -> dict:
    by = {m.code: m for m in run.metrics.all()}
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
    held_grade = 'C' if hard.get('state') == 'held' and raw in 'AB' else raw
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
            {'name': 'Coverage cap', 'held': False, 'detail': 'Not measured yet: evidence coverage (M36) comes later.'},
        ],
        'partial': {'factorsMeasured': measured, 'factors': len(factors)} if measured < len(factors) else None,
        'draftBands': True,
        'exposure': {'value': exposure.get('value'), 'grade': exposure.get('grade'), 'defect': run.score.get('defect')},
    }
    if len(history) > 1:
        out['previous'] = history[-2]['score']
    return out


def exposure_reading(client) -> dict | None:
    """The client's own Exposure reading in the shape the factor map and insurer pages use; pending factors are null."""
    run = SnapshotRun.objects.filter(client=client).order_by('-period', '-version').first()
    if run is None or not run.score.get('factors'):
        return None
    e = run.score.get('exposure', {})
    return {'factors': [f['value'] for f in run.score['factors']], 'venue': e.get('venue', {}).get('value', 1.0),
            'targeting': e.get('targeting', {}).get('value', 1.0), 'volume': e.get('volume', {}).get('value', 1.0),
            'source': f'Measured from records · {run.period:%b %Y}' + (' · partial' if run.score.get('partial') else '') + ' · draft bands'}
