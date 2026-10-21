from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    dependencies = [('uploads', '0001_initial')]
    operations = [lock_table(t) for t in ('uploaded_file', 'internal_list_entry', 'dnc_check', 'rnd_query', 'complaint', 'training_record')]
