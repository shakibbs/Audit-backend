"""Loads a rulebook file into the database, refusing files the spec says must never load (02-rulebook-parameters §2)."""
import hashlib
from pathlib import Path

import yaml
from django.db import transaction

from .apply import apply_update
from .models import RulebookVersion, RuleValue

RULEBOOK_DIR = Path(__file__).resolve().parents[2] / 'rulebook'


class RulebookRefused(Exception):
    pass


def required_keys() -> set[str]:
    """The keys every version must have: those of the reference file (v3.0)."""
    return {r['key'] for r in yaml.safe_load((RULEBOOK_DIR / 'v3.0.yaml').read_text())['rules']}


def check(doc: dict) -> None:
    rules = doc['rules']
    keys = [r['key'] for r in rules]
    by_key = {r['key']: r for r in rules}
    problems = []
    if doc['status'] not in RulebookVersion.Status.values:
        problems.append(f'unknown status {doc["status"]!r}')
    if missing := required_keys() - set(keys):
        problems.append(f'missing keys: {", ".join(sorted(missing))}')
    if unknown := set(keys) - required_keys():
        problems.append(f'unknown keys (typo?): {", ".join(sorted(unknown))}')
    if dupes := {k for k in keys if keys.count(k) > 1}:
        problems.append(f'keys listed twice: {", ".join(sorted(dupes))}')
    weights = by_key.get('vs_rate_weights', {}).get('value') or []
    if weights and round(sum(weights), 6) != 1:
        problems.append(f'vs_rate_weights add up to {sum(weights)}, not 1')
    skew, dedupe = (by_key.get(k, {}).get('value') for k in ('clock_skew_seconds', 'dedupe_window_seconds'))
    if skew is not None and dedupe is not None and dedupe < skew:
        problems.append('dedupe_window_seconds is below clock_skew_seconds')
    for rule in rules:
        if rule['status'] not in RuleValue.Status.values:
            problems.append(f'{rule["key"]}: unknown status {rule["status"]!r}')
        if rule['status'] != 'tbd' and rule.get('value') is None:
            problems.append(f'{rule["key"]}: {rule["status"]} but has no value')
    if doc['status'] == 'approved':
        rows = rules + [{**r, **j} for r in rules for j in r.get('jurisdictions', [])]
        if tbd := sorted({r['key'] for r in rows if r['status'] == 'tbd'}):
            problems.append(f'an approved rulebook may not contain TBD keys: {", ".join(tbd)}')
        if unapproved := sorted(r['key'] for r in rules if r['affects_status'] and r['owner'] != 'Counsel' and not r.get('counsel_approved')):
            problems.append(f'keys that change results need counsel approval: {", ".join(unapproved)}')
    if problems:
        raise RulebookRefused('; '.join(problems))


def _rows(version: RulebookVersion, rule: dict):
    base = {f: rule.get(f) for f in ('section', 'meaning', 'owner', 'status', 'affects_status', 'value', 'provisional', 'variants', 'shown')}
    base.update(counsel_item=rule.get('counsel_item') or '', counsel_approved=bool(rule.get('counsel_approved')),
                effective_from=rule.get('effective_from'), changed_by=rule.get('changed_by', ''),
                approved_by=rule.get('approved_by', ''), source_url=rule.get('source_url', ''))
    yield RuleValue(version=version, key=rule['key'], jurisdiction='US', **base)
    for place in rule.get('jurisdictions', []):
        shown = 'Not set yet' if place.get('status', rule['status']) == 'tbd' else str(place.get('value'))
        yield RuleValue(version=version, key=rule['key'], **{**base, 'jurisdiction': place['jurisdiction'],
                        'status': place.get('status', rule['status']), 'value': place.get('value'),
                        'provisional': place.get('provisional'), 'variants': place.get('variants'), 'shown': shown})


def load(path: Path) -> tuple[RulebookVersion, str]:
    """Returns (version, 'loaded' | 'reloaded' | 'unchanged'). An approved version is never changed once loaded."""
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    doc = yaml.safe_load(raw)
    check(doc)
    existing = RulebookVersion.objects.filter(version=doc['version']).first()
    if existing and existing.file_sha256 == digest:
        return existing, 'unchanged'
    if existing and existing.status == RulebookVersion.Status.APPROVED:
        raise RulebookRefused(f'v{doc["version"]} is approved and cannot change; add a new version instead.')
    with transaction.atomic():
        if existing:
            existing.rules.all().delete()
        version, _ = RulebookVersion.objects.update_or_create(version=doc['version'], defaults={
            'status': doc['status'], 'effective_from': doc['effective_from'], 'source': doc['source'], 'file_sha256': digest})
        RuleValue.objects.bulk_create([row for rule in doc['rules'] for row in _rows(version, rule)])
        reapply_approved(version)
    return version, 'reloaded' if existing else 'loaded'


def reapply_approved(version: RulebookVersion) -> None:
    """Updates approved in the admin panel survive a reload of the file: they are applied again, oldest first."""
    from apps.regulatory.models import RuleUpdate
    for update in RuleUpdate.objects.filter(state=RuleUpdate.State.APPROVED).order_by('approved_at', 'pk'):
        apply_update(version, update.as_update())
