from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    """Certificate claims are client data."""
    dependencies = [('certificates', '0001_initial')]
    operations = [lock_table('certificate_claim')]
