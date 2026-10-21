"""Module 14 step 5: M36 Evidence coverage (metric spec M36, owner decision 2026-10-22). Each scored input counts by
where its data came from — CiV's own capture, an independent source or the client's tools by API: 1 · files the client
uploaded: 0.7 · statements or missing data (worst case): 0 — weighted by its share of the score (factor weight, then
its share within the factor; M10 and M34 twice). Rule-pending and not-measured inputs are outside the score and
outside coverage. Below coverage_cap_floor (0.60, draft) the grade is held at coverage_cap_grade (C)."""
from apps.rulebook.lookup import NoRulebook, RuleSet

from .factors import DOUBLE, FACTORS

GRADE_VALUE = {'A': 1.0, 'B': 1.0, 'C': 1.0, 'D': 0.7, 'S': 0.0, 'N': 0.0}
# where each scored metric's data comes from (source grade): uploads are D, everything read from tools by API is C,
# certificates B, CiV's own page photos A
SOURCE = {'M07': 'D', 'M11': 'D', 'M12': 'D', 'M13': 'D', 'M01': 'C', 'M03': 'B', 'M04': 'A', 'M27': 'A', 'M28': 'A'}
DEFAULT_SOURCE = 'C'


def grade_of(metric: dict) -> str:
    if metric.get('worstCase') or metric.get('state') == 'worst_case':
        return 'N'
    return SOURCE.get(metric['code'], DEFAULT_SOURCE)


def coverage(metrics: list[dict]) -> dict:
    by = {m['code']: m for m in metrics}
    weighted, mix = [], {}
    for _, _, weight, codes in FACTORS:
        inputs = [(c, 2 if c in DOUBLE else 1) for c in codes if c in by and by[c].get('score') is not None]
        total = sum(w for _, w in inputs)
        for code, w in inputs:
            share = weight * w / total
            g = grade_of(by[code])
            weighted.append((share, GRADE_VALUE[g]))
            mix[g] = mix.get(g, 0) + share
    if not weighted:
        return {'code': 'M36', 'value': None, 'display': 'Not measured', 'notMeasured': 'No score computed'}
    all_weight = sum(s for s, _ in weighted)
    value = sum(s * v for s, v in weighted) / all_weight
    return {'code': 'M36', 'value': round(value, 4), 'display': f'{100 * value:.1f}%', 'notMeasured': None,
            'mix': {g: round(s / all_weight, 4) for g, s in sorted(mix.items())}}


def cap(value: float | None, on) -> dict:
    try:
        rules = RuleSet()
        floor = float(rules.get('coverage_cap_floor', on=on).value or 0.6)
        held_at = rules.get('coverage_cap_grade', on=on).value or 'C'
    except (NoRulebook, LookupError):
        floor, held_at = 0.6, 'C'
    if value is None:
        return {'state': 'not_measured', 'floor': floor, 'grade': held_at}
    return {'state': 'held' if value < floor else 'clear', 'value': value, 'floor': floor, 'grade': held_at}
