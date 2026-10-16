"""Failed-job cleanups: a job that failed part-way removed what it had written. Read only, for CiV staff."""
from django.contrib import admin

from apps.admin_panel.base import CivModelAdmin

from .models import PurgeLog


@admin.register(PurgeLog)
class PurgeLogAdmin(CivModelAdmin):
    eyebrow = 'Records'
    page_sub = ('A job that failed part-way leaves nothing half-done: its rows are removed and noted here. The reason is the '
                "error's type only (its message could quote a record). The next run reads those records again.")
    list_display = ('failed_at', 'company', 'job_name', 'rows_removed', 'reason')
    list_filter = ('job_name', 'reason')
    date_hierarchy = 'failed_at'

    @admin.display(description='Company', ordering='client__name')
    def company(self, purge):
        return purge.client.name

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
