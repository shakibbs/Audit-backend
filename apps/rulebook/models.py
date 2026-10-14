"""The Rulebook: every legal setting and parameter, by version, status, place and date. Loaded from rulebook/*.yaml."""
from django.db import models


class RulebookVersion(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft · tests only'
        PROVISIONAL = 'provisional', 'Provisional · CiV staff only'
        APPROVED = 'approved', 'Approved · shown to clients'

    version = models.CharField(max_length=20, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices)
    effective_from = models.DateField()
    source = models.CharField(max_length=200)  # where the values came from (spec, counsel memo, …)
    file_sha256 = models.CharField(max_length=64)  # the loaded file; a changed file reloads a draft or provisional version
    loaded_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rulebook_version'
        ordering = ['-effective_from']

    def __str__(self) -> str:
        return f'Rulebook v{self.version} ({self.status})'


class RuleValue(models.Model):
    """One rule for one place: federal ('US'), a state ('FL') or a court forum ('5th_circuit'), from a date."""
    class Status(models.TextChoices):
        SET = 'set', 'Set'  # decided
        PROPOSED = 'proposed', 'Proposed'  # runs; results are provisional
        TBD = 'tbd', 'TBD'  # never runs in a scored run: RULE_PENDING

    class Owner(models.TextChoices):
        COUNSEL = 'Counsel'
        PRODUCT = 'Product'
        ENGINEERING = 'Engineering'

    version = models.ForeignKey(RulebookVersion, on_delete=models.CASCADE, related_name='rules')
    key = models.CharField(max_length=80)
    jurisdiction = models.CharField(max_length=20, default='US')
    section = models.CharField(max_length=60)
    meaning = models.TextField()
    owner = models.CharField(max_length=20, choices=Owner.choices)
    status = models.CharField(max_length=10, choices=Status.choices)
    counsel_item = models.CharField(max_length=10, blank=True)  # e.g. A6 in the counsel brief
    affects_status = models.BooleanField()  # can change a consent, checkpoint or lead result
    counsel_approved = models.BooleanField(default=False)
    value = models.JSONField(null=True, blank=True)  # the value in force (Set or Proposed)
    provisional = models.JSONField(null=True, blank=True)  # TBD only: used in draft runs and tests, never scored
    variants = models.JSONField(null=True, blank=True)  # {strict, lenient}: both run in draft runs for the impact view
    shown = models.CharField(max_length=300)  # the value in plain words, for the portal
    effective_from = models.DateField(null=True, blank=True)  # empty = in force since before the lookback
    effective_to = models.DateField(null=True, blank=True)
    # Who changed it and who approved it, so a later AI suggestion and its approval are both on record.
    changed_by = models.CharField(max_length=120, blank=True)
    approved_by = models.CharField(max_length=120, blank=True)
    source_url = models.URLField(blank=True)

    class Meta:
        db_table = 'rule_value'
        ordering = ['key', 'jurisdiction', 'effective_from']
        constraints = [models.UniqueConstraint(fields=['version', 'key', 'jurisdiction', 'effective_from'], name='rule_value_unique',
                                               nulls_distinct=False)]
        indexes = [models.Index(fields=['key', 'jurisdiction'])]

    def __str__(self) -> str:
        return f'{self.key} [{self.jurisdiction}] = {self.shown} ({self.status})'
