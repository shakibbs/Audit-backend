"""One connection = one tool at one client, read-only, with its key locked."""
from django.db import models

from apps.clients.models import Client
from apps.connections.crypto import lock, unlock
from apps.connections.providers import PROVIDER_CHOICES, PROVIDERS, Kind


class Status(models.TextChoices):
    NOT_CONNECTED = 'not_connected', 'Not connected'
    WAITING = 'waiting_client', 'Waiting for client'
    UNTESTED = 'untested', 'Saved, not tested'
    CONNECTED = 'connected', 'Connected'
    FAILED = 'failed', 'Failed'
    STALE = 'stale', 'Stale'


class Connection(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='connections')
    provider = models.CharField('tool', max_length=30, choices=PROVIDER_CHOICES)
    kind = models.CharField(max_length=20, choices=Kind.CHOICES, editable=False)
    label = models.CharField(max_length=100, blank=True, help_text='Optional, e.g. "Main dialer" when a client has two.')
    # Locked key, account ID and secret. Never shown again after saving.
    credentials = models.TextField(blank=True, editable=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_CONNECTED, editable=False)
    last_checked_at = models.DateTimeField('last checked', null=True, blank=True, editable=False)
    last_message = models.CharField(max_length=300, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'connection'
        ordering = ['client__name', 'kind', 'provider']

    @property
    def tool(self):
        return PROVIDERS[self.provider]

    @property
    def has_credentials(self) -> bool:
        return bool(self.credentials)

    def set_credentials(self, values: dict) -> None:
        self.credentials = lock({k: v for k, v in values.items() if v})

    def get_credentials(self) -> dict:
        return unlock(self.credentials)

    def save(self, *args, **kwargs):
        self.kind = self.tool.kind
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.client} · {self.tool.name}{f" ({self.label})" if self.label else ""}'
