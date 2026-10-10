"""A ticked onboarding step for a client. Only steps a person ticks are stored; automatic ones are worked out live."""
from django.conf import settings
from django.db import models

from apps.clients.models import Client


class OnboardingTick(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='onboarding_ticks')
    step = models.CharField(max_length=40)
    done_at = models.DateTimeField(auto_now_add=True)
    done_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')

    class Meta:
        db_table = 'onboarding_tick'
        constraints = [models.UniqueConstraint(fields=['client', 'step'], name='one_tick_per_step')]

    def __str__(self):
        return f'{self.client} · {self.step}'
