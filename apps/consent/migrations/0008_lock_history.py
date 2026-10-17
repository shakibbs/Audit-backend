from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    """Client data. A recheck for every client (no client) is seen only in the all-clients scope."""
    dependencies = [('consent', '0007_keep_up_to_date')]
    operations = [lock_table('consent_result_change'), lock_table('consent_recheck')]
