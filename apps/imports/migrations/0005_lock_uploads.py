from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    dependencies = [('imports', '0004_update_and_dialer_uploads')]
    operations = [lock_table('crm_update'), lock_table('dialer_list_entry')]
