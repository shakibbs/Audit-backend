from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    dependencies = [('vendors', '0003_contracts')]
    operations = [lock_table('vendor_contract')]
