"""Missed records: changes a tool's live notices should have sent but the hourly catch-up or weekly check found.
Read only, for CiV staff. Empty while every tool is polled (live notices are off)."""
from django.contrib import admin

from apps.admin_panel.base import CivModelAdmin

from .models import SyncGap


@admin.register(SyncGap)
class SyncGapAdmin(CivModelAdmin):
    eyebrow = 'Records'
    page_sub = ("Records a tool's live feed missed and the hourly catch-up (or weekly full check) found instead, with how late "
                'they were. Stays empty while every tool is read by polling (live notices are switched off).')
    list_display = ('found_at', 'company', 'source_system', 'source_record_id', 'found_by', 'delay')
    list_filter = ('source_system', 'found_by')
    date_hierarchy = 'found_at'

    @admin.display(description='Company', ordering='client__name')
    def company(self, gap):
        return gap.client.name

    @admin.display(description='How late', ordering='delay_seconds')
    def delay(self, gap):
        minutes = gap.delay_seconds // 60
        return f'{minutes // 60} h {minutes % 60} min' if minutes >= 60 else f'{minutes} min'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
