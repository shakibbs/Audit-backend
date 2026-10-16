from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    """Creation records and batches are client data."""
    dependencies = [('imports', '0001_initial')]
    operations = [lock_table('crm_creation'), lock_table('import_batch')]
