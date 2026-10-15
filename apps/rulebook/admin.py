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
    list_display = ('key', 'place', 'shown', 'status_pill', 'owner', 'counsel_item', 'affects', 'version')
    list_filter = ('status', 'owner', 'section', 'jurisdiction', 'affects_status', 'version')
    search_fields = ('key', 'meaning', 'shown', 'counsel_item')
    list_per_page = 200
    fields = ('key', 'jurisdiction', 'section', 'meaning', 'shown', 'status', 'owner', 'counsel_item', 'affects_status',
              'counsel_approved', 'value', 'provisional', 'variants', 'effective_from', 'effective_to', 'version',
              'changed_by', 'approved_by', 'source_url')

    @admin.display(description='Place', ordering='jurisdiction')
    def place(self, rule):
        return 'Federal' if rule.jurisdiction == 'US' else rule.jurisdiction

    @admin.display(description='Status', ordering='status')
    def status_pill(self, rule):
        return format_html('<span class="civ"><span class="pill pill-{}">{}</span></span>', STATUS_PILL[rule.status], rule.get_status_display())

    @admin.display(description='Changes results', boolean=True, ordering='affects_status')
    def affects(self, rule):
        return rule.affects_status

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
