from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    dependencies = [('conversations', '0001_initial')]
    operations = [lock_table('conversation_review')]
