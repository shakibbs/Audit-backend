"""Law changes (FCC orders, court rulings, state laws) and the Rulebook rules each one touches.
Adding one never changes a rule: the rule is changed separately, with approval."""
import re

from django.core.exceptions import ValidationError
from django.db import models

from .wording import banned_words

METRIC_CODE = re.compile(r'^M\d{2}[a-z]?$')


class RegChange(models.Model):
    class Status(models.TextChoices):
        PROPOSED = 'proposed', 'Proposed'
        ADOPTED = 'adopted', 'Adopted'
        IN_FORCE = 'in_force', 'In force'
        COURT_RULING = 'court_ruling', 'Court ruling'

    class Review(models.TextChoices):
        TO_CHECK = 'to_check', 'To check'  # added, not yet checked by counsel
        CHECKED = 'checked', 'Checked by counsel'

    title = models.CharField(max_length=200)
    jurisdiction = models.CharField(max_length=80, help_text='e.g. Federal · FCC, Federal · 7th Circuit, Oregon')
    status = models.CharField(max_length=20, choices=Status.choices)
    announced_on = models.DateField('date')
    effective_from = models.DateField(null=True, blank=True, help_text='Leave empty when the start date is not known yet')
    effective_text = models.CharField('when it applies', max_length=200, help_text='Shown to clients, e.g. "30 days after publication"')
    summary = models.TextField(help_text='Plain words, shown to clients')
    rule_keys = models.JSONField('rules it touches', default=list, blank=True)
    metrics = models.JSONField('metrics it affects', default=list, blank=True)
    source = models.CharField(max_length=200, help_text='e.g. Oregon HB 3865, FCC order of 30 Sep 2026')
    source_url = models.URLField(blank=True)
    review = models.CharField(max_length=20, choices=Review.choices, default=Review.TO_CHECK)
    # Who suggested it: a CiV staff member, or later the AI law watcher (an admin still approves).
    suggested_by = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'reg_change'
        ordering = ['-announced_on']
        verbose_name = 'regulatory change'

    def __str__(self) -> str:
        return self.title

    def clean(self):
        from apps.rulebook.models import RuleValue
        errors = {}
        known = set(RuleValue.objects.values_list('key', flat=True))
        if unknown := [k for k in self.rule_keys if k not in known]:
            errors['rule_keys'] = f'Not in the Rulebook: {", ".join(unknown)}'
        if bad := [m for m in self.metrics if not METRIC_CODE.match(m)]:
            errors['metrics'] = f'Not a metric code (like M10): {", ".join(bad)}'
        for field in ('title', 'summary', 'effective_text'):
            if words := banned_words(getattr(self, field)):
                errors[field] = f'Clients may not see these words: {", ".join(words)}'
        if errors:
            raise ValidationError(errors)


class RuleUpdate(models.Model):
    """A new value for one rule, proposed with a law change. Nothing changes until an admin approves it."""
    class State(models.TextChoices):
        WAITING = 'waiting', 'Draft · waiting for approval'
        APPROVED = 'approved', 'Approved · in the Rulebook'
        REJECTED = 'rejected', 'Rejected'

    class RuleStatus(models.TextChoices):
        SET = 'set', 'Set'
        PROPOSED = 'proposed', 'Proposed'

    reg_change = models.ForeignKey(RegChange, on_delete=models.PROTECT, related_name='rule_updates')
    # The rule this changes. Blank = a brand-new rule: then new_key and new_meaning name it.
    key = models.CharField('modifies rule', max_length=80, blank=True)
    new_key = models.CharField('new rule name', max_length=80, blank=True, help_text='Only for a brand-new rule, e.g. ai_voice_disclosure')
    new_meaning = models.CharField('what the new rule means', max_length=300, blank=True)
    jurisdiction = models.CharField('place', max_length=20, default='US', help_text='US for federal, a state code (OR), or a court forum')
    value = models.JSONField('new value', help_text='Same shape as the current value, e.g. {"start": "08:00", "end": "20:00"}')
    shown = models.CharField('new value in plain words', max_length=300, help_text='Shown to clients, e.g. 8am – 8pm')
    status = models.CharField('rule status', max_length=10, choices=RuleStatus.choices, default=RuleStatus.SET)
    effective_from = models.DateField('starts on')
    state = models.CharField(max_length=10, choices=State.choices, default=State.WAITING)
    proposed_by = models.CharField(max_length=120, blank=True)  # a CiV staff member, or later the AI law watcher
    approved_by = models.CharField(max_length=120, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'rule_update'
        ordering = ['-created_at']
        verbose_name = 'rule update'
        permissions = [('approve_ruleupdate', 'Can approve rule updates (changes the Rulebook)')]

    @property
    def rule_key(self) -> str:
        return self.key or self.new_key

    @property
    def is_new_rule(self) -> bool:
        return not self.key

    def __str__(self) -> str:
        what = 'new rule ' if self.is_new_rule else ''
        return f'{what}{self.rule_key} [{self.jurisdiction}] → {self.shown} from {self.effective_from}'

    def clean(self):
        from apps.rulebook.models import RuleValue
        errors = {}
        known = RuleValue.objects.filter(key=self.rule_key).exists()
        if self.key and not known:
            errors['key'] = 'Not in the Rulebook.'
        if not self.key:
            if not re.fullmatch(r'[a-z][a-z0-9_]{2,79}', self.new_key or ''):
                errors['new_key'] = 'Pick the rule it modifies, or name the new rule (small letters and _, e.g. ai_voice_disclosure).'
            elif known:
                errors['new_key'] = 'This rule already exists: pick it under "Modifies rule".'
            if not self.new_meaning.strip():
                errors['new_meaning'] = 'Say in one line what the new rule means.'
        if self.key and (self.new_key or self.new_meaning):
            errors['new_key'] = 'Leave the new-rule fields blank when you modify an existing rule.'
        self.jurisdiction = (self.jurisdiction or 'US').strip()
        if self.jurisdiction != 'US' and len(self.jurisdiction) == 2:
            self.jurisdiction = self.jurisdiction.upper()
        if words := banned_words(self.shown):
            errors['shown'] = f'Clients may not see these words: {", ".join(words)}'
        if errors:
            raise ValidationError(errors)

    def as_update(self):
        from apps.rulebook.apply import Update
        return Update(key=self.rule_key, new_meaning=self.new_meaning if self.is_new_rule else '', jurisdiction=self.jurisdiction, value=self.value, shown=self.shown, status=self.status,
                      effective_from=self.effective_from, changed_by=self.proposed_by, approved_by=self.approved_by,
                      source_url=self.reg_change.source_url)


class RuleUpdateReview(models.Model):
    """A client's lawyer's view on a draft rule update. Advice only: CiV alone approves."""
    class Verdict(models.TextChoices):
        AGREE = 'agree', 'Agrees'
        DISAGREE = 'disagree', 'Disagrees'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='rule_reviews')
    rule_update = models.ForeignKey(RuleUpdate, on_delete=models.CASCADE, related_name='reviews')
    reviewer = models.ForeignKey('accounts.ClientUser', on_delete=models.SET_NULL, null=True, related_name='rule_reviews')
    reviewer_name = models.CharField(max_length=150)  # kept even if the user is later removed
    verdict = models.CharField(max_length=10, choices=Verdict.choices)
    comment = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rule_update_review'
        constraints = [models.UniqueConstraint(fields=['client', 'rule_update'], name='one_review_per_client')]

    def __str__(self) -> str:
        return f'{self.reviewer_name}: {self.get_verdict_display()}'


class RegChangeRead(models.Model):
    """A client marked a law change as read ("I've read this")."""
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='reg_changes_read')
    reg_change = models.ForeignKey(RegChange, on_delete=models.CASCADE, related_name='reads')
    read_by = models.CharField(max_length=150)
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'reg_change_read'
        constraints = [models.UniqueConstraint(fields=['client', 'reg_change'], name='one_read_per_client')]


class ClientSuggestion(models.Model):
    """A client's lawyer tells CiV about a law change. Never shown to other clients; CiV decides what to add."""
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='suggestions')
    suggested_by = models.CharField(max_length=150)
    title = models.CharField(max_length=200)
    jurisdiction = models.CharField(max_length=80)
    summary = models.TextField()
    source = models.CharField(max_length=200, blank=True)
    source_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    handled = models.BooleanField('handled by CiV', default=False)
    civ_note = models.CharField('CiV note', max_length=300, blank=True)

    class Meta:
        db_table = 'client_suggestion'
        ordering = ['handled', '-created_at']
        verbose_name = 'client suggestion'

    def __str__(self) -> str:
        return self.title
