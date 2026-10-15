"""The four changes from the portal's sample data, marked "to check" for counsel."""
from datetime import date

from django.db import migrations

CHANGES = [
    dict(title='FCC adopts a new order on revoking consent', jurisdiction='Federal · FCC', status='adopted',
         announced_on=date(2026, 9, 30), effective_text='30 days after publication in the Federal Register (not yet published)',
         summary='A caller may treat an opt-out as applying only to the category of informational messages it was aimed at, '
                 'and may designate an exclusive opt-out method. A follow-up proposal asks about shortening the '
                 '10-business-day deadline.',
         rule_keys=['optout_scope_rules', 'optout_deadline_business_days'], metrics=['M08', 'M09', 'M10'],
         source='FCC open meeting, 30 Sep 2026'),
    dict(title='Seventh Circuit: a text is not a “telephone call” for private do-not-call suits',
         jurisdiction='Federal · 7th Circuit', status='court_ruling', announced_on=date(2026, 7, 14),
         effective_text='In force in that circuit',
         summary='In Steidinger v. Blackstone Medical Services the court held that texts fall outside the private '
                 'do-not-call claim. Other courts differ, so results depend on the forum.',
         rule_keys=[], metrics=['M13'], source='Seventh Circuit opinion, 14 Jul 2026'),
    dict(title='Oregon extends its telemarketing law to texts', jurisdiction='Oregon', status='in_force',
         announced_on=date(2026, 1, 1), effective_from=date(2026, 1, 1), effective_text='1 Jan 2026',
         summary='Solicitations are limited to 8am–8pm and to three in 24 hours, and texts are covered.',
         rule_keys=['calling_hours', 'frequency_limits', 'quiet_hours_apply_to_sms'], metrics=['M16', 'M17'],
         source='Oregon HB 3865'),
    dict(title='Texas treats texts as telephone solicitation', jurisdiction='Texas', status='in_force',
         announced_on=date(2025, 9, 1), effective_from=date(2025, 9, 1), effective_text='1 Sep 2025',
         summary='Texts are now covered, sellers must register, and private suits are allowed.',
         rule_keys=['calling_hours', 'state_consent_rule'], metrics=['M16'], source='Texas SB 140'),
]


def add(apps, schema_editor):
    RegChange = apps.get_model('regulatory', 'RegChange')
    for change in CHANGES:
        RegChange.objects.get_or_create(title=change['title'], defaults={**change, 'suggested_by': 'Portal sample data'})


def remove(apps, schema_editor):
    apps.get_model('regulatory', 'RegChange').objects.filter(title__in=[c['title'] for c in CHANGES]).delete()


class Migration(migrations.Migration):
    dependencies = [('regulatory', '0001_initial')]
    operations = [migrations.RunPython(add, remove)]
