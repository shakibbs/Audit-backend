"""Module 16: the document AI's exam (accuracy gate), one per feature: examples with known answers in
exam/<feature>.json. A reading is applied only while the AI in use has passed the latest exam for that feature, with
these instructions. Pass = at least MIN_CASES examples and PASS_MARK right; re-run when the AI or instructions change
and every 30 days. CiV adds more hand-checked examples to the files."""
import json
from datetime import timedelta
from pathlib import Path

from django.utils import timezone

from . import ai
from .models import DocExamRun

FOLDER = Path(__file__).resolve().parent / 'exam'
MIN_CASES = 50
PASS_MARK = 0.95
EVERY = timedelta(days=30)


def cases(feature: str) -> list[dict]:
    path = FOLDER / f'{feature}.json'
    return json.loads(path.read_text()) if path.exists() else []


def right(feature: str, expected: dict, got: dict) -> bool:
    """Every expected answer matches; for contracts only whether each clause was found counts, not the quote."""
    if feature == 'contract_clauses':
        found = {k: bool((v or {}).get('found')) for k, v in (got.get('clauses') or {}).items()}
        return all(found.get(k) == v for k, v in expected.get('clauses', {}).items()) and all(
            got.get(k) == expected[k] for k in ('ends_on', 'dispute_days') if k in expected)
    return all(got.get(k) == v for k, v in expected.items())


def run(feature: str, reader, note: str = '') -> DocExamRun:
    from apps.clients.models import Client
    from .features import FEATURES
    exam, ok, mistakes = cases(feature), 0, []
    stand_in = Client(name='Example Solar Co', brand_names='Example Solar')
    for case in exam:
        try:
            got = reader(feature, case['document'], FEATURES[feature].questions(stand_in)).get('answers') or {}
        except Exception as error:
            got = {'error': type(error).__name__}
        if right(feature, case['expected'], got):
            ok += 1
        else:
            mistakes.append({'case': case['id'], 'got': got})
    passed = len(exam) >= MIN_CASES and ok >= PASS_MARK * len(exam)
    return DocExamRun.objects.create(feature=feature, model=getattr(reader, 'model', 'unknown'), prompt_version=ai.PROMPT_VERSIONS[feature],
                                     cases=len(exam), right=ok, passed=passed, mistakes=mistakes[:50], note=note)


def latest(feature: str, reader) -> DocExamRun | None:
    return DocExamRun.objects.filter(feature=feature, model=getattr(reader, 'model', 'unknown'), prompt_version=ai.PROMPT_VERSIONS[feature]).first()


def trusted(feature: str, reader) -> bool:
    found = latest(feature, reader)
    return bool(found and found.passed)


def due(feature: str, reader, now=None) -> bool:
    found = latest(feature, reader)
    return found is None or found.ran_at <= (now or timezone.now()) - EVERY
