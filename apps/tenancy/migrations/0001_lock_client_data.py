from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    """Module 1's tables of client data: phone-code keys, fingerprints, purge log, daily seals."""
    dependencies = [
        ('keyring', '0001_initial'),
        ('ledger', '0002_fingerprint_anchor_fingerprint_leaf_index_and_more'),
        ('anchoring', '0001_initial'),
    ]
    operations = [lock_table(t) for t in ['client_key', 'fingerprint', 'purge_log', 'merkle_anchor']]
