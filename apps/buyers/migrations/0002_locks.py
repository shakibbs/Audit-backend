from django.db import migrations

from apps.tenancy.sql import lock_buyer_table, lock_table


class Migration(migrations.Migration):
    dependencies = [('buyers', '0001_initial')]
    operations = [lock_buyer_table('buyer_link'), lock_table('buyer_invite')]
