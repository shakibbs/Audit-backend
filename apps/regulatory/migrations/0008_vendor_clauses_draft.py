"""CiV's draft of the vendor contract clauses (Module 12, owner decision 2026-10-22) as a rule update, so the clients'
lawyers can agree, disagree or suggest a change on Regulatory Changes and CiV approves it in the admin panel."""
from datetime import date
from pathlib import Path

import yaml
from django.db import migrations

TITLE = 'CiV draft: clauses each vendor contract must contain'


def add(apps, schema_editor):
    RegChange = apps.get_model('regulatory', 'RegChange')
    RuleUpdate = apps.get_model('regulatory', 'RuleUpdate')
    if RegChange.objects.filter(title=TITLE).exists():
        return
    rules = yaml.safe_load((Path(__file__).resolve().parents[3] / 'rulebook' / 'v3.0.yaml').read_text())['rules']
    value = next(r['value'] for r in rules if r['key'] == 'vendor_required_clauses')
    change = RegChange.objects.create(
        title=TITLE, jurisdiction='CiV draft', status='proposed', announced_on=date(2026, 10, 22), effective_text='When CiV approves it',
        summary=('CiV has no lawyer of its own, so it drafted the clauses a lead vendor contract should contain. Five are required '
                 '(consent naming you, a certificate you can claim, proof within 5 business days kept 5 years, opt-outs passed on, '
                 'indemnity); seven are recommended. Your lawyer can agree, disagree or suggest a change.'),
        rule_keys=['vendor_required_clauses'], metrics=['M07'], domains=['VND'], source='CiV draft for counsel review',
        suggested_by='CiV')
    RuleUpdate.objects.create(reg_change=change, key='vendor_required_clauses', jurisdiction='US', value=value,
                              shown='12 clauses, 5 required', status='set', effective_from=date(2026, 10, 22), proposed_by='CiV (draft)')


def remove(apps, schema_editor):
    apps.get_model('regulatory', 'RuleUpdate').objects.filter(reg_change__title=TITLE).delete()
    apps.get_model('regulatory', 'RegChange').objects.filter(title=TITLE).delete()


class Migration(migrations.Migration):
    dependencies = [('regulatory', '0007_domains')]
    operations = [migrations.RunPython(add, remove)]
