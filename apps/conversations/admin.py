"""Admin (Module 9 step 4): the AI's exam results, extra exam questions, and AI answers waiting for CiV staff
("allowed contact again", the new owner after "wrong number") while the AI has not passed. Staff can re-read a
conversation from the client's tool to decide (in memory, shown once, every opening logged) and report a wrong answer,
which fails the AI's exam at once."""
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from apps.access_log.recorder import record
from apps.admin_panel.base import CivModelAdmin

from . import review as reviewing
from . import speech
from .models import ConversationReview, ExamCase, ExamRun
from .readers import CannotRead, NoRecording, reader_for, recording_reader_for


def pill(color, text):
    return format_html('<span class="civ"><span class="pill pill-{}">{}</span></span>', color, text)


@admin.register(ExamRun)
class ExamRunAdmin(CivModelAdmin):
    eyebrow = 'AI'
    page_sub = ('The AI\'s exam: made-up conversations with known answers. Pass = every stop caught and at least 98 % right, '
                'texts and calls separately. Until it passes, AI stops do not count against clients.')
    list_display = ('ran_at', 'channel', 'model', 'prompt_version', 'result', 'stops_shown', 'right_shown', 'note')
    list_filter = ('channel', 'passed', 'model')
    readonly_fields = ('channel', 'model', 'prompt_version', 'ran_at', 'cases', 'right', 'stops', 'stops_caught', 'passed', 'mistakes', 'note')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='Result')
    def result(self, r):
        return pill('green', 'Passed') if r.passed else pill('red', 'AI failed the exam')

    @admin.display(description='Stops caught')
    def stops_shown(self, r):
        return f'{r.stops_caught} of {r.stops}' if r.stops else '-'

    @admin.display(description='Right')
    def right_shown(self, r):
        return f'{100 * r.right / r.cases:.1f}% ({r.right} of {r.cases})' if r.cases else '-'


EXAMPLE_TURNS = '[\n  {"who": "business", "text": "Hi, is this John?"},\n  {"who": "customer", "text": "Please stop calling me."}\n]'


class TurnsField(forms.JSONField):
    """A new question's Turns box opens empty, with a grey example, never the word "null" (owner, 2026-10-31)."""
    def prepare_value(self, value):
        return '' if value is None else super().prepare_value(value)


@admin.register(ExamCase)
class ExamCaseAdmin(CivModelAdmin):
    eyebrow = 'AI'
    page_sub = 'Extra exam questions written by CiV staff (e.g. after a real mistake). Made-up words only, never client data.'
    list_display = ('added_at', 'channel', 'expected', 'note', 'added_by')
    list_filter = ('channel', 'expected')
    fields = ('channel', 'turns', 'expected', 'moment', 'note')

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == 'turns':
            field = TurnsField(label='Turns', help_text=db_field.help_text, encoder=db_field.encoder, decoder=db_field.decoder)
            field.widget = forms.Textarea(attrs={'rows': 6, 'placeholder': EXAMPLE_TURNS, 'class': 'vLargeTextField'})
            return field
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        obj.added_by = obj.added_by or request.user.email
        super().save_model(request, obj, form, change)


@admin.register(ConversationReview)
class ConversationReviewAdmin(CivModelAdmin):
    eyebrow = 'AI'
    page_sub = ('What the AI decided for each conversation (never the words). While the AI has not passed its exam, '
                '"allowed contact again" and new owners after "wrong number" wait here for CiV staff.')
    list_display = ('reviewed_at', 'company', 'channel', 'result', 'confidence', 'trusted_shown', 'approval_shown', 'read_link')
    list_filter = ('approval', 'result', 'channel', 'trusted', 'reported_wrong', 'client')
    search_fields = ('client__name',)
    actions = ('approve', 'reject', 'report_wrong')
    readonly_fields = [f.name for f in ConversationReview._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='Company', ordering='client__name')
    def company(self, r):
        return r.client.name

    @admin.display(description='Exam passed')
    def trusted_shown(self, r):
        return 'Yes' if r.trusted else 'No'

    @admin.display(description='Staff')
    def approval_shown(self, r):
        if r.reported_wrong:
            return pill('red', 'Reported wrong')
        return pill({'waiting': 'amber', 'approved': 'green', 'rejected': 'red'}[r.approval], r.get_approval_display()) if r.approval else '-'

    @admin.display(description='Conversation')
    def read_link(self, r):
        url = reverse('admin:conversations_conversationreview_read', args=[r.pk])
        return format_html('<a class="civ-btn civ-btn-ghost" href="{}">Read</a>', url)

    @admin.action(description='Approve: carry out the AI answer')
    def approve(self, request, queryset):
        self._decide(request, queryset, True)

    @admin.action(description='Reject: change nothing')
    def reject(self, request, queryset):
        self._decide(request, queryset, False)

    def _decide(self, request, queryset, yes):
        done = 0
        for r in queryset.filter(approval='waiting'):
            reviewing.approve(r, request.user.email, yes)
            record('ai_answer_approved' if yes else 'ai_answer_rejected', request=request, actor_kind='staff', actor_id=request.user.pk,
                   actor_label=request.user.email, client_id=r.client_id, object=f'review {r.pk} · {r.result}')
            done += 1
        messages.info(request, f'{done} waiting answer(s) {"approved" if yes else "rejected"}.')

    @admin.action(description='Report as wrong (fails the AI exam)')
    def report_wrong(self, request, queryset):
        for r in queryset.filter(reported_wrong=False):
            reviewing.report_wrong(r, request.user.email)
            record('ai_answer_reported_wrong', request=request, actor_kind='staff', actor_id=request.user.pk,
                   actor_label=request.user.email, client_id=r.client_id, object=f'review {r.pk} · {r.result}')
        messages.warning(request, 'Reported. The AI is not trusted until it passes its exam again.')

    def get_urls(self):
        return [path('<int:pk>/read/', self.admin_site.admin_view(self.read_view), name='conversations_conversationreview_read'),
                *super().get_urls()]

    def read_view(self, request, pk):
        """Re-read the conversation from the client's tool for this one look; nothing is saved but the log line."""
        if not request.user.has_perm('conversations.view_conversationreview'):
            raise PermissionDenied
        r = get_object_or_404(ConversationReview, pk=pk)
        turns, problem = [], ''
        try:
            if r.channel == 'text':
                found = reader_for(r.client, r.source_system)
                if found is None:
                    raise CannotRead("this tool can't share message text")
                turns, _ = reviewing.thread_of(r.client, r.phone_token, r.source_system, *found)
            else:
                found, transcriber = recording_reader_for(r.client, r.source_system), speech.active()
                if found is None or transcriber is None or r.thread_end is None:
                    raise CannotRead('no recording reader or speech-to-text yet')
                turns = transcriber(found[0](found[1], r.thread_end.source_record_id))
        except (CannotRead, NoRecording) as error:
            problem = str(error) or 'No recording'
        except Exception as error:
            problem = f'The tool did not answer ({type(error).__name__})'
        record('conversation_read', request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
               client_id=r.client_id, object=f'review {r.pk}')
        response = TemplateResponse(request, 'conversations/read.html', {
            **self.admin_site.each_context(request), 'title': 'Conversation', 'review': r, 'turns': turns, 'problem': problem,
            'back_url': reverse('admin:conversations_conversationreview_changelist')})
        response['Cache-Control'] = 'private, no-store'
        return response


def ai_tile(client) -> tuple:
    """Admin client page, top row: this client's AI review this month, and the exam state for texts and calls."""
    from django.utils import timezone

    from . import ai, exam
    start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month = ConversationReview.objects.filter(client=client, reviewed_at__gte=start)
    stops = month.filter(result__in=['opted_out', 'wrong_number']).count()
    waiting = ConversationReview.objects.filter(client=client, approval='waiting').count()
    reviewer = ai.active()
    if reviewer is None:
        state = 'no AI chosen yet'
    else:
        state = ' · '.join(f'{c}s: exam {"passed" if exam.trusted(c, reviewer) else "not passed"}' for c in ('text', 'call'))
    url = reverse('admin:conversations_conversationreview_changelist') + f'?client__id__exact={client.pk}'
    return ('AI review', f'{stops} stop{"" if stops == 1 else "s"}', f'this month ({month.count()} read) · {waiting} waiting · {state}', url)
