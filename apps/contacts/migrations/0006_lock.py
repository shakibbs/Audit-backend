from django.db import migrations

from apps.tenancy.sql import lock_table


class Migration(migrations.Migration):
    """Epochs and CRM number holders are client data."""
    dependencies = [('contacts', '0005_phoneepoch_contactevent_epoch_crmphoneholder_and_more')]
    operations = [lock_table('phone_epoch'), lock_table('crm_phone_holder')]
