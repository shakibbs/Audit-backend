"""lock_table(): the migration step every table of client data gets. Rows are shown only inside the matching scope."""
from django.db import migrations

POLICY = ("current_setting('civ.scope', true) = 'all' "
          "OR client_id = NULLIF(current_setting('civ.client_id', true), '')::bigint")


def lock_table(table: str) -> migrations.RunSQL:
    return migrations.RunSQL(
        f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;'
        f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY;'  # the table's owner must obey too
        f'CREATE POLICY tenant_only ON {table} USING ({POLICY}) WITH CHECK ({POLICY});',
        reverse_sql=f'DROP POLICY IF EXISTS tenant_only ON {table};'
                    f'ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;'
                    f'ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;',
    )


BUYER_POLICY = (f"{POLICY} OR (current_setting('civ.scope', true) = 'buyer' "
                "AND org_id = NULLIF(current_setting('civ.buyer_id', true), '')::bigint)")


def lock_buyer_table(table: str) -> migrations.RunSQL:
    """For tables a buyer may read (Module 15): the company's own rows, or the signed-in buyer's own rows."""
    return migrations.RunSQL(
        f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;'
        f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY;'
        f'CREATE POLICY tenant_or_buyer ON {table} USING ({BUYER_POLICY}) WITH CHECK ({BUYER_POLICY});',
        reverse_sql=f'DROP POLICY IF EXISTS tenant_or_buyer ON {table};'
                    f'ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;'
                    f'ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;',
    )
