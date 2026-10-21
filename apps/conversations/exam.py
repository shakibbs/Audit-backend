"""Step 4, the AI's exam (accuracy gate). Made-up conversations with known right answers (exam/text.json,
exam/call.json, plus ExamCase rows CiV staff add), marked through the same judge() the live review uses.
Owner decision 2026-10-21: pass = every stop caught (100 %) and at least 98 % of all answers right; texts and calls
separately. Re-run when the AI or its instructions change, and every 30 days. A real mistake reported by CiV staff
fails the AI at once. Calls are marked on written turns; speech-to-text is tested with CiV's test calls (step 5)."""
import json
from datetime import timedelta
from pathlib import Path

from django.utils import timezone

from . import ai
from .models import ExamCase, ExamRun

FOLDER = Path(__file__).resolve().parent / 'exam'
STOPS = ('opted_out', 'wrong_number')  # either puts the number on the STOP list
STOP_MARK = 1.0  # conv_review_stop_catch_mark
OVERALL_MARK = 0.98  # conv_review_accuracy_pass_mark
MIN_CASES = 300  # ai_accuracy_min_items
EVERY = timedelta(days=30)


def cases(channel: str) -> list[dict]:
    found = json.loads((FOLDER / f'{channel}.json').read_text())
    for extra in ExamCase.objects.filter(channel=channel):
        found.append({'id': f'staff-{extra.pk}', 'turns': extra.turns, 'expected': extra.expected, 'moment': extra.moment})
    return found


def mark(case: dict, got: str, index) -> tuple[bool, bool]:
    """(right, stop caught). A stop also needs the right moment: the deadline counts from it."""
    moment_ok = case.get('moment') is None or index == case['moment']
    caught = case['expected'] in STOPS and got in STOPS and moment_ok
    return got == case['expected'] and (case['expected'] not in STOPS or moment_ok), caught


def run(channel: str, reviewer, note: str = '') -> ExamRun:
    from .review import judge
    exam = cases(channel)
    right = stops = caught = 0
    mistakes = []
    for case in exam:
        try:
            got, index, _, _ = judge([dict(t) for t in case['turns']], reviewer)
        except Exception as error:  # the AI failed to answer: a wrong answer
            got, index = f'error: {type(error).__name__}', None
        ok, hit = mark(case, got, index)
        right += ok
        if case['expected'] in STOPS:
            stops += 1
            caught += hit
        if not ok:
            mistakes.append({'case': case['id'], 'expected': case['expected'], 'got': got})
    passed = len(exam) >= MIN_CASES and caught >= STOP_MARK * stops and right >= OVERALL_MARK * len(exam)
    return ExamRun.objects.create(channel=channel, model=getattr(reviewer, 'model', 'unknown'), prompt_version=ai.PROMPT_VERSION,
                                  cases=len(exam), right=right, stops=stops, stops_caught=caught, passed=passed,
                                  mistakes=mistakes, note=note)


def latest(channel: str, reviewer) -> ExamRun | None:
    return ExamRun.objects.filter(channel=channel, model=getattr(reviewer, 'model', 'unknown'), prompt_version=ai.PROMPT_VERSION).first()


def trusted(channel: str, reviewer) -> bool:
    """The AI in use passed its latest exam for this channel (with these instructions)."""
    found = latest(channel, reviewer)
    return bool(found and found.passed)


def due(channel: str, reviewer, now=None) -> bool:
    found = latest(channel, reviewer)
    return found is None or found.ran_at <= (now or timezone.now()) - EVERY


def fail_now(channel: str, reviewer, why: str) -> ExamRun:
    """A real mistake was found: the AI is not trusted until it passes again."""
    return ExamRun.objects.create(channel=channel, model=getattr(reviewer, 'model', 'unknown'), prompt_version=ai.PROMPT_VERSION,
                                  passed=False, note=why)
