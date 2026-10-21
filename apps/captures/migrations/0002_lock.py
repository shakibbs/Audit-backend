from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    """Client data: which pages a client's leads came from, and CiV's captures of them."""
    dependencies = [('captures', '0001_initial')]
    operations = [lock_table('consent_page'), lock_table('page_capture')]
