from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    """Proofs are client data."""
    dependencies = [('consent', '0001_initial')]
    operations = [lock_table('consent_proof')]
