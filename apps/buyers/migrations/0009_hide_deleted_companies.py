"""An insurer no longer sees a company CiV staff deleted (it is hidden and switched off, its records kept)."""
from django.db import migrations

SHARED = ("current_setting('civ.scope', true) = 'all' "
          "OR client_id = NULLIF(current_setting('civ.client_id', true), '')::bigint "
          "OR (current_setting('civ.scope', true) = 'buyer' AND client_id IN ("
          "SELECT client_id FROM buyer_link WHERE org_id = NULLIF(current_setting('civ.buyer_id', true), '')::bigint "
          "AND revoked_at IS NULL AND (ends_on IS NULL OR ends_on >= CURRENT_DATE)) "
          "AND client_id NOT IN (SELECT id FROM client WHERE deleted_at IS NOT NULL))")
OLD = ("current_setting('civ.scope', true) = 'all' "
       "OR client_id = NULLIF(current_setting('civ.client_id', true), '')::bigint "
       "OR (current_setting('civ.scope', true) = 'buyer' AND client_id IN ("
       "SELECT client_id FROM buyer_link WHERE org_id = NULLIF(current_setting('civ.buyer_id', true), '')::bigint "
       "AND revoked_at IS NULL AND (ends_on IS NULL OR ends_on >= CURRENT_DATE)))")


class Migration(migrations.Migration):
    dependencies = [('buyers', '0008_alter_buyerinvite_email_alter_buyeruser_email'), ('clients', '0008_deleted_companies_kept')]
    operations = [migrations.RunSQL(
        f'DROP POLICY IF EXISTS shared_with_buyer ON attestation_snapshot; '
        f'CREATE POLICY shared_with_buyer ON attestation_snapshot USING ({SHARED}) WITH CHECK ({SHARED});',
        reverse_sql=f'DROP POLICY IF EXISTS shared_with_buyer ON attestation_snapshot; '
                    f'CREATE POLICY shared_with_buyer ON attestation_snapshot USING ({OLD}) WITH CHECK ({OLD});')]
