"""Admin: proof requests. CiV staff open the file the client attached and mark it valid (with the consent date it
shows) or not valid. Every opening is logged."""
from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.access_log.recorder import record
from apps.admin_panel.base import CivModelAdmin

from .models import ProofRequest
from .requests import review


class ReviewForm(forms.ModelForm):
    class Meta:
        model = ProofRequest
        fields = ('review', 'consent_date', 'review_note')

    def clean(self):
        data = super().clean()
        if data.get('review') == ProofRequest.Review.VALID and not data.get('consent_date'):
            self.add_error('consent_date', 'A valid proof needs the date it shows consent was given.')
        if data.get('review') and self.instance.answer != ProofRequest.Answer.PROOF:
            self.add_error('review', 'Only an attached file can be checked.')
        return data


@admin.register(ProofRequest)
class ProofRequestAdmin(CivModelAdmin):
    eyebrow = 'Records'
    page_sub = ('Numbers from uploaded lists that CiV asked clients to prove. Open the file, then mark it valid with the '
                'consent date it shows, or not valid. Until checked, the calls stay "Weak".')
    form = ReviewForm
    list_display = ('sent_at', 'company', 'masked_label', 'batch_label', 'answer_shown', 'review_shown')
    list_filter = ('answer', 'review', 'file_type', 'client')
    search_fields = ('client__name', 'masked_label', 'batch_label')
    fields = ('company', 'batch_label', 'masked_label', 'due_at', 'answer', 'answered_at', 'answered_by', 'file_type', 'open_file',
              'file_sha256', 'review', 'consent_date', 'review_note', 'reviewed_by', 'reviewed_at')
    readonly_fields = ('company', 'batch_label', 'masked_label', 'due_at', 'answer', 'answered_at', 'answered_by', 'file_type',
                       'open_file', 'file_sha256', 'reviewed_by', 'reviewed_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='Company', ordering='client__name')
    def company(self, r):
        return r.client.name

    @admin.display(description='Answer')
    def answer_shown(self, r):
        return r.get_answer_display() if r.answer else ('Overdue' if r.due_at < timezone.now() else 'Waiting')

    @admin.display(description='Check')
    def review_shown(self, r):
        if r.answer != ProofRequest.Answer.PROOF:
            return '-'
        color = {'valid': 'green', 'invalid': 'red'}.get(r.review, 'amber')
        return format_html('<span class="civ"><span class="pill pill-{}">{}</span></span>', color, r.get_review_display())

    @admin.display(description='File')
    def open_file(self, r):
        if not r.file:
            return 'Deleted after 4 years' if r.purged_at else '-'
        url = reverse('admin:provenance_proofrequest_file', args=[r.pk])
        return format_html('<a class="civ-btn" href="{}" target="_blank" rel="noopener">Open {}</a>', url, r.original_name or 'file')

    def save_model(self, request, obj, form, change):
        if 'review' in form.changed_data or 'consent_date' in form.changed_data:
            if obj.review:
                review(obj, request.user.email, valid=obj.review == ProofRequest.Review.VALID, consent_date=obj.consent_date, note=obj.review_note)
                record('proof_reviewed', request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
                       client_id=obj.client_id, object=f'{obj} · {obj.get_review_display()}'[:254])
                return
        super().save_model(request, obj, form, change)

    def get_urls(self):
        return [path('<int:pk>/file/', self.admin_site.admin_view(self.file_view), name='provenance_proofrequest_file'), *super().get_urls()]

    def file_view(self, request, pk):
        if not request.user.has_perm('provenance.view_proofrequest'):
            raise PermissionDenied
        r = get_object_or_404(ProofRequest, pk=pk)
        if not r.file:
            raise Http404
        record('proof_file_opened', request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
               client_id=r.client_id, object=str(r)[:254])
        response = FileResponse(r.file.open('rb'), as_attachment=True, filename=r.original_name or 'proof')
        response['Cache-Control'] = 'private, no-store'
        return response


def provenance_tile(client) -> tuple:
    """Admin client page, top row: share of this month's called numbers that are untraced, and proof files to check."""
    from django.utils import timezone

    from .api import month_bounds
    from .models import Provenance
    start, end = month_bounds(timezone.localdate())
    month = Provenance.objects.filter(client=client, first_contact_at__date__gte=start, first_contact_at__date__lte=end)
    total = month.count()
    untraced = month.filter(basis='untraced').count()
    to_check = ProofRequest.objects.filter(client=client, answer=ProofRequest.Answer.PROOF, review='').count()
    url = reverse('admin:provenance_proofrequest_changelist') + f'?client__id__exact={client.pk}'
    value = f'{round(100 * untraced / total)}%' if total else '-'
    return ('Lead provenance', value, f'untraced this month · {to_check} proof file(s) to check', url)
