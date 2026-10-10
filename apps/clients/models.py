"""A client company. Every client user and every result belongs to exactly one client."""
from django.db import models


class Client(models.Model):
    class Plan(models.TextChoices):
        STARTER = 'starter', 'Starter'
        GROWTH = 'growth', 'Growth'
        ENTERPRISE = 'enterprise', 'Enterprise'

    name = models.CharField(max_length=200, unique=True)
    industry = models.CharField(max_length=100, blank=True)
    plan = models.CharField(max_length=20, choices=Plan.choices, default=Plan.GROWTH)
    start_date = models.DateField()
    # Counsel-directed by default: findings and alerts go only to users marked as the client's lawyer.
    counsel_directed = models.BooleanField('lawyer-only mode', default=True)
    # 0–4, from connected tools; set by the connections module, never typed in.
    access_level = models.PositiveSmallIntegerField(default=0, editable=False)
    class Status(models.TextChoices):
        TRIAL = 'trial', 'Trial'
        ONBOARDING = 'onboarding', 'Onboarding'
        ACTIVE = 'active', 'Active'
        PAUSED = 'paused', 'Paused'
        ENDED = 'ended', 'Ended'

    status = models.CharField('stage', max_length=20, choices=Status.choices, default=Status.ONBOARDING)
    status_changed_at = models.DateTimeField(null=True, blank=True, editable=False)
    # Follows the status (Ended = off); sign-in, invites and resets check it. Never edited by hand.
    is_active = models.BooleanField(default=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'client'
        ordering = ['name']
        verbose_name = 'client company'
        verbose_name_plural = 'client companies'

    # Live sync reads the client's tools only in these stages.
    @property
    def can_sync(self) -> bool:
        return self.status in (self.Status.TRIAL, self.Status.ONBOARDING, self.Status.ACTIVE)

    def __str__(self):
        return self.name


class StatusChange(models.Model):
    """One move from a stage to another: when, who and why."""
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='status_changes')
    old_status = models.CharField(max_length=20, choices=Client.Status.choices, blank=True)
    new_status = models.CharField(max_length=20, choices=Client.Status.choices)
    reason = models.CharField(max_length=300, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey('staff.StaffUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        db_table = 'client_status_change'
        ordering = ['-changed_at']
