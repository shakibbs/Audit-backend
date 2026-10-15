from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    """Bookmarks and gaps are client data."""
    dependencies = [('sync', '0001_initial')]
    operations = [lock_table(t) for t in ['sync_cursor', 'sync_gap']]
