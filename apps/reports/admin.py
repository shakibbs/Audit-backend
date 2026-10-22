"""Admin: every client report, so CiV staff see a blocked one (a banned word in its text) and fix the wording."""
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html

from apps.access_log.recorder import record
from apps.admin_panel.base import CivModelAdmin

from .models import Report


@admin.register(Report)
class ReportAdmin(CivModelAdmin):
    eyebrow = 'Records'
    page_sub = 'Client reports. A blocked report had a banned word in its text and was not released; fix the wording, then the client makes it again.'
    list_display = ('made_at', 'client', 'name', 'period', 'status', 'banned_shown', 'made_by')
    list_filter = ('status', 'client')
    # The file is private (no public address): a Download button through CiV, logged (bug fix 2026-10-23).
    exclude = ('file', 'banned')
    readonly_fields = [f.name for f in Report._meta.fields if f.name not in ('file', 'banned')] + ['banned_shown', 'download']

    @admin.display(description='Banned words')
    def banned_shown(self, report):
        return ', '.join(report.banned) if report.banned else 'None'

    @admin.display(description='File')
    def download(self, report):
        if not report.pk or not report.file:
            return '-'
        return format_html('<a class="civ-btn" href="{}">Download</a>', reverse('admin:reports_report_download', args=[report.pk]))

    def get_urls(self):
        return [path('<int:pk>/download/', self.admin_site.admin_view(self.download_view), name='reports_report_download'),
                *super().get_urls()]

    def download_view(self, request, pk):
        if not request.user.has_perm('reports.view_report'):
            raise PermissionDenied
        report = get_object_or_404(Report, pk=pk)
        if not report.file:
            raise Http404
        record('report_downloaded', request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
               client_id=report.client_id, object=f'{report.name} {report.period:%b %Y}'[:254])
        kind = report.file.name.rsplit('.', 1)[-1]
        response = FileResponse(report.file.open('rb'), as_attachment=True, filename=f'{report.name}-{report.period:%Y-%m}.{kind}'.replace(' ', '-'))
        response['Cache-Control'] = 'private, no-store'
        return response

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
