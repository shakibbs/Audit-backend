from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    dependencies = [('onboarding', '0002_setupmark')]
    operations = [lock_table('setup_mark')]
