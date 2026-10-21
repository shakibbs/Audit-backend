from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    dependencies = [('evidence', '0001_initial')]
    operations = [lock_table('refetch_check')]
