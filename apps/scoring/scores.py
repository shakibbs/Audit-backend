"""Module 10 step 2: each metric becomes a 0–100 score (100 = best), so different metrics can be added up.
- a share where higher is better (e.g. M01 consent coverage %) → the score is the share;
- a count of problems → per 10,000 contacts in the month: 0 → 100, up to 5 → 50, more → 0;
- M08 hours to stop, M09 share not honored, M31 abandoned %, M32 manual-import %, M35 reassigned per 10,000: own bands.
Bands come from the Rulebook (`metric_score_bands`, draft). Not yet measured / rule pending → no score (left out);
worst case (the client did not supply the data) → 0 (owner decision 2026-10-12)."""
from apps.rulebook.lookup import NoRulebook, RuleSet

DRAFT_BANDS = {'count_per_10k': [[0, 100], [5, 50]], 'M08': [[24, 100], [72, 50]], 'M09': [[0, 100], [0.1, 50]],
               'M31': [[1, 100], [3, 50]], 'M32': [[5, 100], [20, 50]], 'M35': [[0, 100], [5, 50]]}
SHARE_GOOD = {'M01', 'M03', 'M04', 'M06', 'M07', 'M11', 'M25b', 'M27', 'M28', 'M42'}  # percentages, higher is better
COUNTS = {'M10', 'M12', 'M13', 'M15', 'M16', 'M17', 'M18', 'M19', 'M20', 'M21', 'M26', 'M34', 'M38', 'M41', 'M45', 'M48'}


def bands(on=None) -> dict:
    try:
        found = RuleSet().get('metric_score_bands', on=on).value
    except (NoRulebook, KeyError, LookupError):
        found = None
    return {**DRAFT_BANDS, **(found or {})}


def banded(x: float, steps: list) -> float:
    """[[limit, score], ...]: the first limit x is at or under gives the score; above every limit → 0."""
    for limit, score in steps:
        if x <= limit:
            return float(score)
    return 0.0


def score(metric: dict, state: str, contacts: int, table: dict) -> float | None:
    if state == 'worst_case':
        return 0.0
    if state != 'measured':
        return None
    code, value = metric['code'], metric.get('value')
    if code == 'M08':
        return 0.0 if metric.get('display') == 'NEVER' else (banded(value, table['M08']) if value is not None else None)
    if code == 'M09':
        done = metric.get('pastDeadline') or 0
        return banded(metric.get('notHonored', 0) / done, table['M09']) if done else None
    if value is None:
        return None
    if code in ('M31', 'M32'):
        return banded(value, table[code])
    if code == 'M35':
        return banded(10_000 * value / contacts, table['M35']) if contacts else None
    if code in SHARE_GOOD:
        return max(0.0, min(100.0, float(value)))
    if code in COUNTS:
        return banded(10_000 * value / contacts, table['count_per_10k']) if contacts else (100.0 if value == 0 else None)
    return None  # not a scored metric (display, loss model…)
