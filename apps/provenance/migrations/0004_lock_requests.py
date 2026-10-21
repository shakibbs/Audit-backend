from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    dependencies = [('provenance', '0003_proof_requests')]
    operations = [lock_table('proof_request')]
