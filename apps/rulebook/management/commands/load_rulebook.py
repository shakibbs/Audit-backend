"""Loads every rulebook/*.yaml file. Runs on each deploy; files that did not change are skipped."""
from django.core.management.base import BaseCommand

from apps.rulebook.loader import RULEBOOK_DIR, load


class Command(BaseCommand):
    help = 'Load the rulebook files in rulebook/ into the database.'

    def handle(self, *args, **options):
        for path in sorted(RULEBOOK_DIR.glob('*.yaml')):
            version, result = load(path)
            self.stdout.write(f'{path.name}: v{version.version} {version.status}, {version.rules.count()} rows, {result}')
