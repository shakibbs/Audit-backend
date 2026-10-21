from django.db import migrations

from apps.tenancy.sql import lock_buyer_table

# rating_engine has no company: only CiV's jobs and the insurer's own people see its row.
ORG_ONLY = ("current_setting('civ.scope', true) = 'all' OR (current_setting('civ.scope', true) = 'buyer' "
            "AND org_id = NULLIF(current_setting('civ.buyer_id', true), '')::bigint)")


class Migration(migrations.Migration):
    dependencies = [('buyers', '0005_rating_engine')]
    operations = [
        lock_buyer_table('rating_send'),
        migrations.RunSQL(
            'ALTER TABLE rating_engine ENABLE ROW LEVEL SECURITY; ALTER TABLE rating_engine FORCE ROW LEVEL SECURITY;'
            f'CREATE POLICY org_only ON rating_engine USING ({ORG_ONLY}) WITH CHECK ({ORG_ONLY});',
            reverse_sql='DROP POLICY IF EXISTS org_only ON rating_engine; ALTER TABLE rating_engine NO FORCE ROW LEVEL SECURITY;'
                        'ALTER TABLE rating_engine DISABLE ROW LEVEL SECURITY;'),
    ]
