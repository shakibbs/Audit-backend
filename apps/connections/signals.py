"""Keeps the client's access level up to date whenever a connection changes."""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.connections.access_level import refresh_access_level
from apps.connections.models import Connection


@receiver([post_save, post_delete], sender=Connection)
def connection_changed(sender, instance, **kwargs):
    refresh_access_level(instance.client)
