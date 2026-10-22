"""Rulebook page: every rule, read only. Rules change in rulebook/*.yaml (pushed and reviewed); edit and approve come later."""
from django.contrib import admin
from django.utils.html import format_html

from apps.admin_panel.base import CivModelAdmin

from .models import RuleValue

STATUS_PILL = {'set': 'green', 'proposed': 'amber', 'tbd': 'gray'}


@admin.register(RuleValue)
class RuleValueAdmin(CivModelAdmin):
    eyebrow = 'Rules'
    page_sub = ('Every legal setting and parameter the engine uses, by place and date. Read only: rules change in the '
                'Rulebook file, reviewed and pushed. Set = decided · Proposed = runs, results provisional · '
                'TBD = never scored (rule pending).')
    list_display = ('key', 'place', 'shown', 'status_pill', 'owner', 'counsel_item', 'affects', 'version', 'history_link')
    list_filter = ('status', 'owner', 'section', 'jurisdiction', 'affects_status', 'version')
    search_fields = ('key', 'meaning', 'shown', 'counsel_item')
    list_per_page = 200
    fields = ('key', 'jurisdiction', 'section', 'meaning', 'shown', 'status', 'owner', 'counsel_item', 'affects_status',
              'counsel_approved', 'value', 'provisional_shown', 'variants_shown', 'effective_from', 'effective_to', 'version',
              'changed_by', 'approved_by', 'source_url')

    # Empty draft and variant values show a dash, not "null" (2026-10-23).
    @admin.display(description='Provisional')
    def provisional_shown(self, rule):
        return '-' if rule.provisional in (None, '', [], {}) else rule.provisional

    @admin.display(description='Variants')
    def variants_shown(self, rule):
        return '-' if rule.variants in (None, '', [], {}) else rule.variants

    @admin.display(description='Place', ordering='jurisdiction')
    def place(self, rule):
        return 'Federal' if rule.jurisdiction == 'US' else rule.jurisdiction

    @admin.display(description='Status', ordering='status')
    def status_pill(self, rule):
        return format_html('<span class="civ"><span class="pill pill-{}">{}</span></span>', STATUS_PILL[rule.status], rule.get_status_display())

    @admin.display(description='History')
    def history_link(self, rule):
        from django.urls import reverse
        return format_html('<a href="{}">History</a>', reverse('admin:rulebook_rulevalue_rule_history', args=[rule.key]))

    def get_urls(self):
        from django.urls import path
        return [path('check/', self.admin_site.admin_view(self.check_view), name='rulebook_rulevalue_check'),
                # Own name and address: Django's admin already has a "history" page per row (owner bug fix, 2026-10-23).
                path('rule-history/<str:key>/', self.admin_site.admin_view(self.rule_history_view), name='rulebook_rulevalue_rule_history'),
                *super().get_urls()]

    def check_view(self, request):
        from django.template.response import TemplateResponse

        from .health import check
        return TemplateResponse(request, 'rulebook/check.html', {**self.admin_site.each_context(request), 'title': 'Rulebook check', 'data': check()})

    def history_view(self, request, object_id, extra_context=None):
        """The History button on a rule's page opens the rule's own history (all its values over time)."""
        from django.shortcuts import redirect
        from django.urls import reverse
        rule = self.get_object(request, object_id)
        if rule is None:
            return super().history_view(request, object_id, extra_context)
        return redirect(reverse('admin:rulebook_rulevalue_rule_history', args=[rule.key]))

    def rule_history_view(self, request, key):
        from django.template.response import TemplateResponse
        from django.urls import reverse

        from .health import history
        return TemplateResponse(request, 'rulebook/history.html', {**self.admin_site.each_context(request), 'title': f'History · {key}',
                                                                   'key': key, 'rows': history(key), 'back_url': reverse('admin:rulebook_rulevalue_check')})

    @admin.display(description='Changes results', boolean=True, ordering='affects_status')
    def affects(self, rule):
        return rule.affects_status

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
