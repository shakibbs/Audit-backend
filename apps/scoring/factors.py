"""Module 10 step 3: the six factors and D (Exposure Indicator v2.2). Each factor is 100 minus the weighted mean of its
metrics' scores (higher = worse); M10 and M34 count twice. Owner decisions 2026-10-21:
- a factor with no scored metric is "pending": left out of D, its weight spread over the measured factors, D "partial";
- any contact after an in-scope opt-out (M10) or an internal-list entry (M12) holds F3 / F2 at 75 or worse;
- display-only metrics (M38, M41, M42, M45, M48…) are shown but never scored here."""
FACTORS = [
    ('F1', 'Consent defensibility', 0.28, ['M01', 'M03', 'M04']),
    ('F2', 'Suppression integrity', 0.20, ['M12', 'M13']),
    ('F3', 'Revocation and opt-out', 0.17, ['M08', 'M09', 'M10', 'M34']),
    ('F4', 'Calling conduct', 0.16, ['M15', 'M16', 'M17', 'M18', 'M19', 'M20', 'M31']),
    ('F5', 'Vendor and lead provenance', 0.11, ['M06', 'M07', 'M25b', 'M26', 'M27', 'M28', 'M32']),
    ('F6', 'Call integrity', 0.08, ['M11', 'M21', 'M35']),
]
DOUBLE = {'M10', 'M34'}
CAP = 75.0
CAPPED_BY = {'F2': 'M12', 'F3': 'M10'}  # contact after an internal-list entry / an opt-out


def violated(metric: dict | None) -> bool:
    return bool(metric) and (metric.get('worstCase') or (metric.get('value') or 0) > 0)


def factors(metrics: list[dict]) -> dict:
    by = {m['code']: m for m in metrics}
    out = []
    for key, name, weight, codes in FACTORS:
        scored = [(by[c]['score'], 2 if c in DOUBLE else 1) for c in codes if c in by and by[c].get('score') is not None]
        value = None
        if scored:
            value = round(100 - sum(s * w for s, w in scored) / sum(w for _, w in scored), 1)
        held = key in CAPPED_BY and violated(by.get(CAPPED_BY[key])) and (value is None or value < CAP)
        if held:
            value = CAP
        out.append({'key': key, 'name': name, 'weight': weight, 'value': value, 'pending': value is None,
                    'metrics': [c for c in codes if c in by and by[c].get('score') is not None],
                    **({'heldBy': CAPPED_BY[key]} if held else {})})
    measured = [f for f in out if not f['pending']]
    total = sum(f['weight'] for f in measured)
    defect = round(sum(f['value'] * f['weight'] for f in measured) / total, 1) if measured else None
    return {'factors': out, 'defect': defect, 'partial': len(measured) < len(out)}
