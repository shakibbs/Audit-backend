from django.db import migrations

from apps.tenancy.sql import lock_table

# A buyer reads a company's attestations only while that company shares with it (Module 15).
SHARED = ("current_setting('civ.scope', true) = 'all' "
          "OR client_id = NULLIF(current_setting('civ.client_id', true), '')::bigint "
          "OR (current_setting('civ.scope', true) = 'buyer' AND client_id IN ("
          "SELECT client_id FROM buyer_link WHERE org_id = NULLIF(current_setting('civ.buyer_id', true), '')::bigint "
          "AND revoked_at IS NULL AND (ends_on IS NULL OR ends_on >= CURRENT_DATE)))")


class Migration(migrations.Migration):
    dependencies = [('buyers', '0003_attestation')]
    operations = [
        lock_table('insured_statement'),
        migrations.RunSQL(
            'ALTER TABLE attestation_snapshot ENABLE ROW LEVEL SECURITY;'
            'ALTER TABLE attestation_snapshot FORCE ROW LEVEL SECURITY;'
            f'CREATE POLICY shared_with_buyer ON attestation_snapshot USING ({SHARED}) WITH CHECK ({SHARED});',
            reverse_sql='DROP POLICY IF EXISTS shared_with_buyer ON attestation_snapshot;'
                        'ALTER TABLE attestation_snapshot NO FORCE ROW LEVEL SECURITY;'
                        'ALTER TABLE attestation_snapshot DISABLE ROW LEVEL SECURITY;'),
    ]
