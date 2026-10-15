"""Regulatory changes page: CiV staff add the law changes clients see on the portal's Regulatory Changes page."""
from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join
from django.views.decorators.http import require_POST
from unfold.admin import TabularInline

from apps.access_log.recorder import record
from apps.admin_panel.base import CivModelAdmin

from .approve import approve, reject
from .forms import RegChangeForm, RuleUpdateForm
from .models import ClientSuggestion, RegChange, RuleUpdate
from apps.rulebook.apply import OverlapRefused

STATUS_PILL = {'proposed': 'gray', 'adopted': 'teal', 'in_force': 'green', 'court_ruling': 'amber'}


class RuleUpdateInline(TabularInline):
    """The "Rule updates" tab: new rule values this law change brings. They wait until an admin approves them."""
    model = RuleUpdate
    form = RuleUpdateForm
    tab = True
    extra = 0
    verbose_name = 'rule update'
    verbose_name_plural = 'Rule updates'
    fields = ('key', 'new_key', 'new_meaning', 'jurisdiction', 'value', 'shown', 'status', 'effective_from', 'state', 'lawyers', 'decide')
    readonly_fields = ('state', 'lawyers', 'decide')

    def has_delete_permission(self, request, obj=None):
        return False  # a rejected update stays on record

    @admin.display(description="Clients' lawyers")
    def lawyers(self, update):
        """What the clients' lawyers said in the portal. Advice only: the decision is CiV's."""
        if not update.pk:
            return '-'
        reviews = list(update.reviews.select_related('client'))
        if not reviews:
            return 'No reviews yet'
        agree = sum(r.verdict == 'agree' for r in reviews)
        lines = format_html_join('', '<div class="tiny">{} ({}): <b>{}</b>{}</div>', (
            (r.reviewer_name, r.client.name, r.get_verdict_display(), f' · “{r.comment}”' if r.comment else '') for r in reviews))
        return format_html('<span class="civ"><b>{} agree · {} disagree</b>{}</span>', agree, len(reviews) - agree, lines)

    @admin.display(description='Approve')
    def decide(self, update):
        """Approve / Reject buttons. They send this page's form to the approve view, which uses only the update's ID."""
        if not update.pk:
            return 'Save first'
        if update.state != RuleUpdate.State.WAITING:
            return update.approved_by or '-'
        if not self.can_approve:
            return 'Waiting for an approver'
        buttons = '<button type="submit" class="civ-btn" formaction="{}" formnovalidate>Approve</button> ' \
                  '<button type="submit" class="civ-btn civ-btn-ghost" formaction="{}" formnovalidate>Reject</button>'
        return format_html(buttons, reverse('admin:regulatory_ruleupdate_decide', args=[update.pk, 'approve']),
                           reverse('admin:regulatory_ruleupdate_decide', args=[update.pk, 'reject']))

    def get_formset(self, request, obj=None, **kwargs):
        self.can_approve = request.user.has_perm('regulatory.approve_ruleupdate')
        return super().get_formset(request, obj, **kwargs)


@admin.register(RegChange)
class RegChangeAdmin(CivModelAdmin):
    eyebrow = 'Rules'
    page_sub = ('New laws, orders and court rulings, with the Rulebook rules each one touches. On a change\'s '
                '"Rule updates" tab, add the new value of a rule (or a brand-new rule): it stays a draft until an admin '
                'clicks Approve, then the Rulebook uses it from its start date.')
    form = RegChangeForm
    list_display = ('title', 'jurisdiction', 'status_pill', 'announced_on', 'rules', 'review_pill')
    list_filter = ('status', 'review', 'jurisdiction')
    search_fields = ('title', 'summary', 'source', 'jurisdiction')
    date_hierarchy = 'announced_on'
    readonly_fields = ('suggested_by', 'created_at', 'updated_at')
    inlines = [RuleUpdateInline]

    @admin.display(description='Status', ordering='status')
    def status_pill(self, change):
        return format_html('<span class="civ"><span class="pill pill-{}">{}</span></span>', STATUS_PILL[change.status], change.get_status_display())

    @admin.display(description='Rules it touches')
    def rules(self, change):
        return ', '.join(change.rule_keys) or '-'

    @admin.display(description='Counsel', ordering='review')
    def review_pill(self, change):
        color = 'green' if change.review == RegChange.Review.CHECKED else 'amber'
        return format_html('<span class="civ"><span class="pill pill-{}">{}</span></span>', color, change.get_review_display())

    def save_model(self, request, change, form, is_change):
        if not is_change:
            change.suggested_by = request.user.email
        super().save_model(request, change, form, is_change)
        record('reg_change_changed' if is_change else 'reg_change_added', request=request, actor_kind='staff',
               actor_id=request.user.pk, actor_label=request.user.email, object=change.title[:254])

    def save_formset(self, request, form, formset, change):
        for update in formset.save(commit=False):
            if not update.pk:
                update.proposed_by = request.user.email
            update.save()
        formset.save_m2m()

    def get_urls(self):
        decide = self.admin_site.admin_view(require_POST(self.decide_view))
        return [path('rule-update/<int:pk>/<str:verb>/', decide, name='regulatory_ruleupdate_decide')] + super().get_urls()

    def decide_view(self, request, pk, verb):
        """Approve writes the update into the Rulebook from its start date; Reject keeps it on record, unused."""
        update = get_object_or_404(RuleUpdate, pk=pk)
        back = redirect('admin:regulatory_regchange_change', update.reg_change_id)
        if not request.user.has_perm('regulatory.approve_ruleupdate') or verb not in ('approve', 'reject'):
            self.message_user(request, 'You cannot approve rule updates.', messages.ERROR)
            return back
        if update.state != RuleUpdate.State.WAITING:
            return back
        if verb == 'reject':
            reject(update, request.user)
            self.message_user(request, f'Rejected: {update}', messages.SUCCESS)
            return back
        try:
            approve(update, request.user)
            self.message_user(request, f'Approved and now in the Rulebook: {update}', messages.SUCCESS)
        except OverlapRefused as error:
            self.message_user(request, f'Not approved: {error}', messages.ERROR)
        return back

    def delete_model(self, request, change):
        record('reg_change_removed', request=request, actor_kind='staff', actor_id=request.user.pk,
               actor_label=request.user.email, object=change.title[:254])
        super().delete_model(request, change)



@admin.register(ClientSuggestion)
class ClientSuggestionAdmin(CivModelAdmin):
    eyebrow = 'Rules'
    page_sub = ("Law changes that clients' lawyers told us about in the portal. Only CiV sees them. If one is right, "
                'add it under Regulatory changes, then tick "Handled".')
    list_display = ('title', 'jurisdiction', 'company', 'suggested_by', 'created_at', 'handled')
    list_filter = ('handled', 'jurisdiction')
    search_fields = ('title', 'summary', 'source')
    fields = ('title', 'jurisdiction', 'summary', 'source', 'source_url', 'company', 'suggested_by', 'created_at', 'handled', 'civ_note')
    readonly_fields = ('title', 'jurisdiction', 'summary', 'source', 'source_url', 'company', 'suggested_by', 'created_at')

    @admin.display(description='Company')
    def company(self, suggestion):
        return suggestion.client.name

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
