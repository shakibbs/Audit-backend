from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    dependencies = [('docai', '0001_initial')]
    operations = [lock_table('doc_reading')]
