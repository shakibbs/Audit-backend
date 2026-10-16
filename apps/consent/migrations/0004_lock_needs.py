from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    dependencies = [('consent', '0003_consentneed')]
    operations = [lock_table('consent_need')]
