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
from .models import ClientSuggestion, LawItem, RegChange, RuleUpdate
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


@admin.register(LawItem)
class LawItemAdmin(CivModelAdmin):
    """Module 13 step 1: what the law watcher found. Read the source, then add a law change (Regulatory changes) or
    dismiss the item. Nothing here changes the Rulebook."""
    eyebrow = 'Rules'
    page_sub = ('New FCC rules and proposed rules from the Federal Register that mention calling or texting, found every '
                'morning. Open the source; if it changes a rule, add it under Regulatory changes. Otherwise dismiss it.')
    list_display = ('level_shown', 'published_on', 'stage', 'title_shown', 'rules_shown', 'state')
    list_filter = ('state', 'level', 'stage', 'kind', 'source')
    search_fields = ('title', 'summary', 'ref')
    readonly_fields = [f.name for f in LawItem._meta.fields if f.name != 'state']
    fields = ('make_change_button', 'title', 'kind', 'level_shown', 'stage_shown', 'published_on', 'effective_on', 'agencies', 'summary', 'source_link',
              'current_rules', 'ai_draft', 'dockets_shown', 'follows_shown', 'matched_shown', 'state')
    actions = ('dismiss',)

    def has_add_permission(self, request):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [*self.readonly_fields, 'make_change_button', 'source_link', 'level_shown', 'stage_shown', 'rules_shown', 'current_rules', 'ai_draft', 'dockets_shown', 'follows_shown',
                'matched_shown']

    @admin.display(description='Stage')
    def stage_shown(self, item):
        return {'proposed': 'Proposed (not law yet)', 'final': 'Final (not in force yet)', 'in_force': 'In force'}.get(item.stage, item.stage)

    @admin.display(description='Law change')
    def make_change_button(self, item):
        if item.reg_change_id:
            url = reverse('admin:regulatory_regchange_change', args=[item.reg_change_id])
            return format_html('<a class="civ-btn civ-btn-ghost" href="{}">Open its law change</a>', url)
        url = reverse('admin:regulatory_lawitem_make_change', args=[item.pk])
        return format_html('<a class="civ-btn" href="{}">Create a law change from this item</a>', url)

    def get_urls(self):
        return [path('<int:pk>/make-change/', self.admin_site.admin_view(self.make_change_view), name='regulatory_lawitem_make_change'),
                *super().get_urls()]

    def make_change_view(self, request, pk):
        from django.core.exceptions import PermissionDenied
        from django.template.response import TemplateResponse

        from .from_item import make_change
        if not request.user.has_perm('regulatory.add_regchange'):
            raise PermissionDenied
        item = get_object_or_404(LawItem, pk=pk)
        if request.method == 'POST':
            change = make_change(item, request.user)
            messages.success(request, 'Law change created. Check its summary and rule updates, then it goes to the lawyers for review.')
            return redirect('admin:regulatory_regchange_change', change.pk)
        drafts = sum(1 for d in item.ai_drafts if d.get('known') and d.get('quote'))
        return TemplateResponse(request, 'regulatory/create_change.html', {
            **self.admin_site.each_context(request), 'title': 'Create a law change', 'item': item, 'drafts': drafts,
            'back_url': reverse('admin:regulatory_lawitem_change', args=[item.pk])})

    @admin.display(description="AI's draft")
    def ai_draft(self, item):
        if item.ai_done_at is None:
            from .drafting import active
            return 'No AI chosen yet: read the source and write the summary yourself.' if active() is None else 'Waiting for the AI (drafted each morning).'
        sure = f' · {100 * item.ai_confidence:.0f}% sure' if item.ai_confidence is not None else ''
        head = format_html('<p><strong>Summary</strong> ({}, read the {}{}): {}</p>', item.ai_model,
                           'full document' if item.ai_read == 'full_text' else 'official summary', sure, item.ai_summary or '-')
        rows = format_html_join('', '<div><code>{}</code> → <strong>{}</strong> from {} <span class="tiny">“{}”{}</span></div>',
                                ((d['key'], d.get('shown') or d.get('value'), d.get('effective_from') or 'no date given', d['quote'][:300],
                                  '' if d.get('known') else ' · not a rule CiV has') for d in item.ai_drafts))
        return format_html('{}{}<p class="tiny">A draft only: check each value against its sentence in the source.</p>', head, rows or 'No value drafted.')

    @admin.display(description='FCC case numbers')
    def dockets_shown(self, item):
        return ', '.join(item.dockets) or 'None given'

    @admin.display(description='Follows the proposal')
    def follows_shown(self, item):
        if item.follows is None:
            return 'None'
        url = reverse('admin:regulatory_lawitem_change', args=[item.follows_id])
        return format_html('<a href="{}">{}</a>', url, item.follows)

    @admin.display(description='Calling words found')
    def matched_shown(self, item):
        return ', '.join(item.matched) or '-'

    @admin.display(description='Title')
    def title_shown(self, item):
        return item.title[:140]

    def get_queryset(self, request):
        from django.db.models import Case, IntegerField, Value, When
        order = Case(When(level='High', then=Value(0)), When(level='Medium', then=Value(1)), default=Value(2), output_field=IntegerField())
        return super().get_queryset(request).annotate(rank=order).order_by('rank', '-published_on')

    @admin.display(description='Level', ordering='rank')
    def level_shown(self, item):
        color = {'High': 'red', 'Medium': 'amber'}.get(item.level, 'gray')
        return format_html('<span class="civ"><span class="pill pill-{}">{}</span></span>', color, item.level)

    @admin.display(description='Rules it may touch')
    def rules_shown(self, item):
        return ', '.join(item.rule_keys) or 'None found'

    @admin.display(description='Existing rules it may change (value in force today)')
    def current_rules(self, item):
        from datetime import date

        from apps.rulebook.lookup import NoRulebook, RuleSet
        try:
            rules = RuleSet('internal')
        except NoRulebook:
            rules = None
        lines = []
        for key in item.rule_keys:
            if key.startswith('M'):
                lines.append((key, 'a metric CiV measures, not a Rulebook value', ''))
                continue
            try:
                rule = rules.get(key, on=date.today()) if rules else None
            except LookupError:
                rule = None
            if rule is None:
                lines.append((key, 'not in the Rulebook', ''))
            else:
                since = f'since {rule.effective_from:%-d %b %Y}' if rule.effective_from else 'since the start'
                lines.append((key, f'now {rule.shown}', f'{rule.status.capitalize()} · {since}'))
        if not lines:
            return 'None found'
        return format_html_join('', '<div><code>{}</code>: <strong>{}</strong> <span class="tiny">{}</span></div>', lines)

    @admin.display(description='Source')
    def source_link(self, item):
        return format_html('<a class="civ-btn civ-btn-ghost" href="{}" target="_blank" rel="noopener">Open in the Federal Register ↗</a>', item.url)

    @admin.action(description='Dismiss: not a calling-rule change')
    def dismiss(self, request, queryset):
        n = queryset.exclude(state=LawItem.State.DISMISSED).update(state=LawItem.State.DISMISSED)
        record('law_items_dismissed', request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email, object=f'{n} items')
        messages.info(request, f'{n} item(s) dismissed.')
