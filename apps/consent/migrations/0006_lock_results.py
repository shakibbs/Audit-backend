from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    dependencies = [('consent', '0005_consent_result')]
    operations = [lock_table('consent_result')]
