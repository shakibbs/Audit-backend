from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    """Contacts are client data."""
    dependencies = [('contacts', '0001_initial')]
    operations = [lock_table('contact_event')]
