from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    dependencies = [('scoring', '0001_initial')]
    operations = [lock_table('snapshot_run'), lock_table('metric_snapshot')]
