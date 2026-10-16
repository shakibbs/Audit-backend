"""The lookup every check uses: rule('calling_hours', on=date, state='FL').

Most specific place first: the state (or court forum), then federal ('US'). A place's own rule wins even when it is
still TBD: a pending Florida rule is never replaced by the federal one, which may be looser.
"""
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from .models import RulebookVersion, RuleValue

RULE_PENDING = 'RULE_PENDING'


class UnknownRule(KeyError):
    pass


class NoRulebook(LookupError):
    pass


class RulePending(Exception):
    """Raised by Rule.require() when the rule has no decided value yet."""
    def __init__(self, rule: 'Rule'):
        super().__init__(f'{rule.key} [{rule.jurisdiction}] is TBD ({RULE_PENDING})')
        self.rule = rule


@dataclass(frozen=True)
class Rule:
    key: str
    jurisdiction: str
    value: object  # None while pending
    status: str  # set | proposed | tbd
    counsel_item: str
    shown: str
    version: str
    effective_from: date | None

    @property
    def pending(self) -> bool:
        """No decided value: a scored check returns not_run with reason RULE_PENDING."""
        return self.value is None and self.status == 'tbd'

    @property
    def provisional(self) -> bool:
        """Runs, but the result is marked provisional: the value is Proposed, or a test value stands in for TBD."""
        return self.status != 'set'

    def require(self):
        if self.pending:
            raise RulePending(self)
        return self.value


# Which versions a run may use: clients see approved rulebooks only; CiV's internal runs may use provisional ones;
# draft runs and tests may use anything, including TBD test values.
MODES = {'client': ['approved'], 'internal': ['approved', 'provisional'], 'draft': ['approved', 'provisional', 'draft']}


def current_version(mode: str = 'internal') -> RulebookVersion:
    version = RulebookVersion.objects.filter(status__in=MODES[mode]).order_by('-effective_from').first()
    if version is None:
        raise NoRulebook(f'No rulebook a {mode} run may use.')
    return version


@lru_cache(maxsize=8)
def _rows(version_id: int, file_sha256: str, revision: int) -> dict[str, list[RuleValue]]:
    """Every row of a version, by key, read once per process (a reloaded file or an approved update reads them again)."""
    by_key: dict[str, list[RuleValue]] = {}
    for row in RuleValue.objects.filter(version_id=version_id):
        by_key.setdefault(row.key, []).append(row)
    return by_key


class RuleSet:
    """One rulebook version, held in memory for a run: rules = RuleSet(); rules.get('calling_hours', on=d, state='FL')."""

    def __init__(self, mode: str = 'internal', version: RulebookVersion | None = None):
        self.mode = mode
        self.version = version or current_version(mode)
        self._by_key = _rows(self.version.pk, self.version.file_sha256, self.version.revision)

    def get(self, key: str, *, on: date, state: str | None = None, forum: str | None = None, variant: str | None = None) -> Rule:
        rows = self._by_key.get(key)
        if not rows:
            raise UnknownRule(key)
        in_force = [r for r in rows if (r.effective_from is None or r.effective_from <= on) and (r.effective_to is None or on <= r.effective_to)]
        for place in [p for p in (state, forum) if p] + ['US']:
            matches = [r for r in in_force if r.jurisdiction.upper() == place.upper()]
            if matches:
                return self._answer(max(matches, key=lambda r: r.effective_from or date.min), variant)
        raise UnknownRule(f'{key}: nothing in force on {on}')

    def _answer(self, row: RuleValue, variant: str | None) -> Rule:
        value = row.value
        if self.mode == 'draft':  # tests and the impact view: a chosen variant, or the TBD test value
            if variant and row.variants and variant in row.variants:
                value = row.variants[variant]
            elif row.status == 'tbd':
                value = row.provisional
        elif variant and row.variants and variant in row.variants and row.status != 'set':
            value = row.variants[variant]  # an undecided key runs both ways (strict and lenient); both results are kept
        elif row.status == 'tbd':
            value = None
        return Rule(row.key, row.jurisdiction, value, row.status, row.counsel_item, row.shown, self.version.version, row.effective_from)


def rule(key: str, *, on: date, state: str | None = None, forum: str | None = None, mode: str = 'internal', variant: str | None = None) -> Rule:
    """One lookup. For many lookups in a run, make one RuleSet and reuse it."""
    return RuleSet(mode).get(key, on=on, state=state, forum=forum, variant=variant)
