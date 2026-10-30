"""Admin: every client report, so CiV staff see a blocked one (a banned word in its text) and fix the wording."""
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html

from apps.access_log.recorder import record
from apps.admin_panel.base import CivModelAdmin

from .models import QuoteRequest, Report


@admin.register(Report)
class ReportAdmin(CivModelAdmin):
    eyebrow = 'Records'
    page_sub = 'Client reports. A blocked report had a banned word in its text and was not released; fix the wording, then the client makes it again.'
    list_display = ('made_at', 'client', 'name', 'period', 'status', 'banned_shown', 'made_by')
    list_filter = ('status', 'client')
    # The file is private (no public address): a Download button through CiV, logged (bug fix 2026-10-23).
    exclude = ('file', 'banned')
    readonly_fields = [f.name for f in Report._meta.fields if f.name not in ('file', 'banned')] + ['banned_shown', 'download']

    # Plain words (owner, 2026-10-31): "None found" in grey, or the words that held the report back in red.
    @admin.display(description='Banned words')
    def banned_shown(self, report):
        if not report.banned:
            return format_html('<span class="civ"><span class="tiny">{}</span></span>', 'None found')
        return format_html('<span class="civ"><span class="pill pill-red">{}</span></span>', ', '.join(report.banned))

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


@admin.register(QuoteRequest)
class QuoteRequestAdmin(CivModelAdmin):
    eyebrow = 'Clients'
    page_sub = ('Litigation evidence package requests. 1 Contact the client and agree the price (write it in the note), then '
                'Accept. 2 The client types the numbers in the portal and CiV makes the package. 3 Download and check it, fill '
                'in the custodian name and title, then Release. The client downloads it. Mark done closes a request.')
    list_display = ('asked_at', 'client', 'name', 'asked_by', 'asked_by_email', 'state')
    list_filter = ('status', ('done_at', admin.EmptyFieldListFilter), 'client')
    fields = ('client', 'name', 'period', 'asked_by', 'asked_by_email', 'asked_at', 'state', 'accepted_at', 'accepted_by',
              'made_at', 'made_by', 'package_shown', 'custodian_name', 'custodian_title', 'released_at', 'released_by',
              'done_at', 'done_by', 'note', 'steps')
    readonly_fields = ('client', 'name', 'period', 'asked_by', 'asked_by_email', 'asked_at', 'state', 'accepted_at', 'accepted_by',
                       'made_at', 'made_by', 'package_shown', 'released_at', 'released_by', 'done_at', 'done_by', 'steps')
    actions = ['accept', 'mark_done']

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        # No Save buttons here (owner, 2026-10-30): the note and custodian are kept by the step buttons below.
        return super().changeform_view(request, object_id, form_url, {**(extra_context or {}), 'show_save': False,
                                                                       'show_save_and_continue': False})

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and obj.done_at:  # closed: nothing left to press, so nothing to type
            return self.readonly_fields + ('custodian_name', 'custodian_title', 'note')
        return self.readonly_fields

    @admin.display(description='State')
    def state(self, q):
        return f'Done {q.done_at:%d %b %Y}' if q.done_at else q.get_status_display()

    @admin.display(description='Package')
    def package_shown(self, q):
        if not q.package:
            return 'Not made yet (the client sends the numbers after you accept)'
        return format_html('{} number(s) found, {} not found · sha256 {} <a class="civ-btn" href="{}">Download</a>', q.package_files,
                           q.package_missing, q.package_sha256[:16] + '…', reverse('admin:reports_quoterequest_download', args=[q.pk]))

    @admin.display(description='Next step')
    def steps(self, q):
        if not q.pk or q.done_at:
            return '-'
        button = '<button type="submit" class="civ-btn" formaction="{}" formnovalidate data-civ-keeps-form>{}</button>'
        url = lambda name: reverse('admin:reports_quoterequest_step', args=[q.pk, name])  # noqa: E731
        done = format_html(button, url('done'), 'Mark done (client contacted)')
        if q.status == QuoteRequest.Status.ASKED:
            return format_html('{} {}', format_html(button, url('accept'), 'Accept (price agreed)'), done)
        if q.status == QuoteRequest.Status.CHECKING:
            return format_html('{} {} {}', format_html(button, url('release'), 'Release to the client'),
                               format_html(button, url('accept'), 'Ask the client for the numbers again'), done)
        waiting = 'Waiting for the client to send the numbers.' if q.status == QuoteRequest.Status.ACCEPTED else 'Released.'
        return format_html('{} {}', waiting, done)

    def get_urls(self):
        return [path('<int:pk>/download/', self.admin_site.admin_view(self.download_view), name='reports_quoterequest_download'),
                path('<int:pk>/step/<str:step>/', self.admin_site.admin_view(self.step_view), name='reports_quoterequest_step'),
                *super().get_urls()]

    def download_view(self, request, pk):
        from .api import send_package
        if not request.user.has_perm('reports.view_quoterequest'):
            raise PermissionDenied
        q = get_object_or_404(QuoteRequest, pk=pk)
        if not q.package:
            raise Http404
        return send_package(request, q, 'staff')

    def step_view(self, request, pk, step):
        from django.contrib import messages
        from django.shortcuts import redirect
        if request.method != 'POST' or not request.user.has_perm('reports.change_quoterequest'):
            raise PermissionDenied
        q = get_object_or_404(QuoteRequest, pk=pk)
        back = redirect('admin:reports_quoterequest_change', q.pk)
        if not q.done_at and 'note' in request.POST and request.POST['note'] != q.note:  # the button sends the whole form: keep the note typed
            q.note = request.POST['note']
            q.save(update_fields=['note'])
        if q.done_at:
            messages.error(request, 'This request is already done.')
        elif step == 'done':
            self._done(request, q)
            messages.success(request, 'Marked done. The client can ask again.')
        elif step == 'accept':
            self._accept(request, q)
            messages.success(request, 'Accepted. The client can now type the numbers in the portal.')
        elif step == 'release':
            name, title = request.POST.get('custodian_name', '').strip()[:150], request.POST.get('custodian_title', '').strip()[:150]
            if q.status != QuoteRequest.Status.CHECKING or not q.package:
                messages.error(request, 'There is no package to release yet.')
            elif not (name and title):
                messages.error(request, 'Fill in the custodian name and title first: they go into the declaration.')
            else:
                from .litigation import release
                q.custodian_name, q.custodian_title = name, title
                release(q, request.user.email)
                record('litigation_package_released', request=request, actor_kind='staff', actor_id=request.user.pk,
                       actor_label=request.user.email, client_id=q.client_id, object=f'{q} · sha256 {q.package_sha256}'[:254])
                self._tell(q, 'Your litigation evidence package is ready', 'CiV checked your package; you can download it now.')
                messages.success(request, 'Released. The client can download it from Reports & Exports.')
        else:
            raise Http404
        return back

    def _accept(self, request, q):
        from django.utils import timezone
        if q.done_at or q.status not in (QuoteRequest.Status.ASKED, QuoteRequest.Status.CHECKING):
            return
        q.status, q.accepted_at, q.accepted_by = QuoteRequest.Status.ACCEPTED, timezone.now(), request.user.email
        q.save(update_fields=['status', 'accepted_at', 'accepted_by'])
        record('quote_request_accepted', request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
               client_id=q.client_id, object=str(q)[:254])
        self._tell(q, 'CiV accepted your request', 'Type the phone numbers for your litigation evidence package on its card (up to 25).')

    def _tell(self, q, heading, line):
        import logging
        from .emails import to_client
        try:
            to_client(q, heading, line)
        except Exception:  # a mail problem never stops a step; the portal shows it either way
            logging.getLogger(__name__).exception('Quote email failed for %s', q.pk)

    @admin.action(description='Accept (price agreed)')
    def accept(self, request, queryset):
        for q in queryset:
            self._accept(request, q)
        self.message_user(request, 'Accepted. The client can now type the numbers in the portal.')

    def _done(self, request, q):
        from django.utils import timezone
        q.done_at, q.done_by = timezone.now(), request.user.email
        q.save(update_fields=['done_at', 'done_by'])
        record('quote_request_done', request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
               client_id=q.client_id, object=str(q)[:254])

    @admin.action(description='Mark done (client contacted)')
    def mark_done(self, request, queryset):
        for q in queryset.filter(done_at__isnull=True):
            self._done(request, q)
        self.message_user(request, 'Marked done. The client can ask again.')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
