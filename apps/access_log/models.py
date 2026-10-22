"""Who did what, and when. Rows are written once and never edited or deleted."""
from django.db import models


class AccessEntry(models.Model):
    class ActorKind(models.TextChoices):
        CLIENT_USER = 'client_user', 'Client user'
        STAFF = 'staff', 'CiV staff'
        SYSTEM = 'system', 'System'
        BUYER = 'buyer', 'Insurer or acquirer'
        ANONYMOUS = 'anonymous', 'Not signed in'

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor_kind = models.CharField(max_length=20, choices=ActorKind.choices)
    actor_id = models.BigIntegerField(null=True, blank=True)
    actor_label = models.CharField(max_length=254, blank=True)
    client_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    action = models.CharField(max_length=64, db_index=True)
    object = models.CharField(max_length=254, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = 'access_log'
        ordering = ['-at']
        verbose_name = 'access log entry'
        verbose_name_plural = 'access log'

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionError('Access log rows cannot be changed.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('Access log rows cannot be deleted.')

    def __str__(self):
        from .labels import action_label
        return f'{self.at:%-d %b %Y · %H:%M} · {action_label(self.action)[0]}'
