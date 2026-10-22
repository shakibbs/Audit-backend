from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    dependencies = [('alerts', '0003_alert_emailed_at_emailchoice')]
    operations = [lock_table('alert_email_choice')]
