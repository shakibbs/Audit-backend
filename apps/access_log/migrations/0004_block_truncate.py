"""The log can only grow: TRUNCATE (emptying the whole table at once) is refused too, like UPDATE and DELETE
(QA 2026-10-23)."""
from django.db import migrations

LOCK = """
CREATE FUNCTION access_log_block_truncate() RETURNS trigger AS $$
BEGIN
  -- Only the automatic tests' own throw-away database (named test_…) may be emptied between tests.
  IF current_database() LIKE 'test\_%' THEN
    RETURN NULL;
  END IF;
  RAISE EXCEPTION 'access_log cannot be emptied';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER access_log_no_truncate
BEFORE TRUNCATE ON access_log
FOR EACH STATEMENT EXECUTE FUNCTION access_log_block_truncate();
"""

UNLOCK = """
DROP TRIGGER access_log_no_truncate ON access_log;
DROP FUNCTION access_log_block_truncate();
"""


class Migration(migrations.Migration):
    dependencies = [('access_log', '0003_buyer_actor')]
    operations = [migrations.RunSQL(LOCK, UNLOCK)]
