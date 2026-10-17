"""Sent when the rules in force change: an approved rule update (from its start date) or a changed Rulebook file.
Results that used the rules listen and check the affected contacts again."""
from django.dispatch import Signal

rules_changed = Signal()  # kwargs: from_date (date or None = every date)
