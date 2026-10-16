from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    """The STOP list and re-added numbers are client data."""
    dependencies = [('optouts', '0001_initial')]
    operations = [lock_table('opt_out_event'), lock_table('optout_readded')]
