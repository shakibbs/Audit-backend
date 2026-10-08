"""Database-level lock: refuse UPDATE and DELETE on access_log, even from bulk queries."""
from django.db import migrations

LOCK = """
CREATE FUNCTION access_log_block_changes() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'access_log rows cannot be changed or deleted';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER access_log_no_update_or_delete
BEFORE UPDATE OR DELETE ON access_log
FOR EACH ROW EXECUTE FUNCTION access_log_block_changes();
"""

UNLOCK = """
DROP TRIGGER access_log_no_update_or_delete ON access_log;
DROP FUNCTION access_log_block_changes();
"""


class Migration(migrations.Migration):
    dependencies = [('access_log', '0001_initial')]
    operations = [migrations.RunSQL(LOCK, UNLOCK)]
