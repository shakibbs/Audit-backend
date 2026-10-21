from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    dependencies = [('optouts', '0004_mark_check')]
    operations = [lock_table('optout_mark_check')]
