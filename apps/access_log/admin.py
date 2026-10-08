"""Access log section of the admin panel: read-only for everyone."""
from django.contrib import admin
from django.utils.html import format_html

from apps.access_log.labels import action_label
from apps.access_log.models import AccessEntry
from apps.admin_panel.base import CivModelAdmin
from apps.clients.models import Client


@admin.register(AccessEntry)
class AccessEntryAdmin(CivModelAdmin):
    eyebrow = 'Records'
    page_sub = 'Every sign-in, sign-out and change. Rows can never be edited or deleted. Times are UTC.'
    list_display = ('when', 'who', 'what', 'object_shown', 'company', 'ip_address')
    list_filter = ('actor_kind', 'action')
    search_fields = ('actor_label', 'action', 'object')
    date_hierarchy = 'at'

    @admin.display(description='When', ordering='at')
    def when(self, entry):
        return format_html('<span class="civ"><span class="mono tiny">{}</span></span>', entry.at.strftime('%d %b %Y · %H:%M'))

    # Before sign-in there is no actor, so the email that was tried is shown.
    @admin.display(description='Who')
    def who(self, entry):
        return entry.actor_label or entry.object or entry.get_actor_kind_display()

    @admin.display(description='What', ordering='action')
    def what(self, entry):
        text, color = action_label(entry.action)
        return format_html('<span class="civ"><span class="pill pill-{}">{}</span></span>', color, text)

    @admin.display(description='Object')
    def object_shown(self, entry):
        return entry.object if entry.actor_label else ''

    # One query for all company names on the page, not one per row.
    def changelist_view(self, request, extra_context=None):
        self.company_names = dict(Client.objects.values_list('pk', 'name'))
        return super().changelist_view(request, extra_context)

    @admin.display(description='Company')
    def company(self, entry):
        return getattr(self, 'company_names', {}).get(entry.client_id, '')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
