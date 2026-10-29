from django.db import migrations

from apps.tenancy.sql import lock_table


def old_rows(apps, schema_editor):
    """The old "Not available yet" history rows (2026-10-30): a litigation one becomes a quote request; the evidence file
    and certification pack ones are dropped (those are made from the bulk export)."""
    Report, QuoteRequest = apps.get_model('reports', 'Report'), apps.get_model('reports', 'QuoteRequest')
    for r in Report.objects.filter(status='unavailable', name='Litigation evidence package'):
        q = QuoteRequest.objects.create(client_id=r.client_id, name=r.name, period=r.period, asked_by=r.made_by)
        QuoteRequest.objects.filter(pk=q.pk).update(asked_at=r.made_at)
    Report.objects.filter(status='unavailable').delete()


class Migration(migrations.Migration):
    dependencies = [('reports', '0004_quote_requests')]
    operations = [lock_table('client_quote_request'), migrations.RunPython(old_rows, migrations.RunPython.noop)]
