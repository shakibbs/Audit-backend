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
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'client'
        ordering = ['name']
        verbose_name = 'client company'
        verbose_name_plural = 'client companies'

    def __str__(self):
        return self.name
