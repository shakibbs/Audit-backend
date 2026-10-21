from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    dependencies = [('alerts', '0001_initial')]
    operations = [lock_table('alert')]
