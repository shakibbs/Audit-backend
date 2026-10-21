"""Admin: every client report, so CiV staff see a blocked one (a banned word in its text) and fix the wording."""
from django.contrib import admin

from apps.admin_panel.base import CivModelAdmin

from .models import Report


@admin.register(Report)
class ReportAdmin(CivModelAdmin):
    eyebrow = 'Records'
    page_sub = 'Client reports. A blocked report had a banned word in its text and was not released; fix the wording, then the client makes it again.'
    list_display = ('made_at', 'client', 'name', 'period', 'status', 'banned', 'made_by')
    list_filter = ('status', 'client')
    readonly_fields = [f.name for f in Report._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
