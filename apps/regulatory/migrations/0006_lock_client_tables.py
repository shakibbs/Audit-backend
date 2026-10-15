from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    """Lawyers' reviews, "read" marks and suggestions are client data: each client sees only its own."""
    dependencies = [('regulatory', '0005_clientsuggestion_regchangeread_ruleupdatereview')]
    operations = [lock_table(t) for t in ['rule_update_review', 'reg_change_read', 'client_suggestion']]
