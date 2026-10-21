from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    dependencies = [('evidence', '0003_legal_hold')]
    operations = [lock_table('legal_hold')]
