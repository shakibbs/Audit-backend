from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    """Reconciliation rows and monthly integrity are client data."""
    dependencies = [('reconcile', '0001_initial')]
    operations = [lock_table('reconciliation'), lock_table('period_integrity')]
