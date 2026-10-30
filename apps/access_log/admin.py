"""Access log section of the admin panel: read-only for everyone."""
from django.contrib import admin
from django.utils.html import format_html

from apps.access_log.labels import action_label
from apps.access_log.labels import who as who_of
from apps.access_log.models import AccessEntry
from apps.admin_panel.base import CivModelAdmin
from apps.clients.models import Client


class Within(admin.SimpleListFilter):
    """The Dashboard's "Sign-ins · 24 h" tile opens the last 24 hours (2026-10-30)."""
    title = 'when'
    parameter_name = 'within'

    def lookups(self, request, model_admin):
        return [('24h', 'Last 24 hours'), ('7d', 'Last 7 days')]

    def queryset(self, request, queryset):
        from datetime import timedelta

        from django.utils import timezone
        hours = {'24h': 24, '7d': 24 * 7}.get(self.value())
        return queryset.filter(at__gte=timezone.now() - timedelta(hours=hours)) if hours else queryset


class What(admin.SimpleListFilter):
    """The "What" filter in plain words, A–Z, like the What column (owner, 2026-10-31): never codes like sign_in_failed.
    Same address as before (?action__exact=), so the Dashboard's links keep working."""
    title = 'what'
    parameter_name = 'action__exact'

    def lookups(self, request, model_admin):
        actions = AccessEntry.objects.values_list('action', flat=True).distinct()
        return sorted(((a, action_label(a)[0]) for a in actions), key=lambda pair: pair[1].lower())

    def queryset(self, request, queryset):
        return queryset.filter(action=self.value()) if self.value() else queryset


@admin.register(AccessEntry)
class AccessEntryAdmin(CivModelAdmin):
    eyebrow = 'Records'
    page_sub = 'Every sign-in, sign-out and change. Rows can never be edited or deleted. Times are UTC.'
    list_display = ('when', 'who', 'what', 'object_shown', 'company', 'ip_address')
    list_filter = (Within, 'actor_kind', What)
    search_fields = ('actor_label', 'action', 'object')
    date_hierarchy = 'at'

    @admin.display(description='When', ordering='at')
    def when(self, entry):
        return format_html('<span class="civ"><span class="mono tiny">{}</span></span>', entry.at.strftime('%d %b %Y · %H:%M'))

    @admin.display(description='Who')
    def who(self, entry):
        return who_of(entry)

    @admin.display(description='What', ordering='action')
    def what(self, entry):
        text, color = action_label(entry.action)
        return format_html('<span class="civ"><span class="pill pill-{}">{}</span></span>', color, text)

    @admin.display(description='Object')
    def object_shown(self, entry):
        return entry.object or '-'

    # One entry's page in plain words: no raw action code, actor kind, actor id or company number (2026-10-23).
    fields = ('when', 'who', 'what', 'object_shown', 'company', 'ip_address')
    readonly_fields = fields

    # One query for all company names on the page, not one per row.
    def changelist_view(self, request, extra_context=None):
        self.company_names = dict(Client.objects.values_list('pk', 'name'))
        return super().changelist_view(request, extra_context)

    @admin.display(description='Company')
    def company(self, entry):
        names = getattr(self, 'company_names', None)
        if names is None:  # one entry's own page
            return Client.objects.filter(pk=entry.client_id).values_list('name', flat=True).first() or '-'
        return names.get(entry.client_id, '')

    # Lets a client page link to its own entries: ?client_id__exact=<id>
    def lookup_allowed(self, lookup, value, request=None):
        return lookup == 'client_id__exact' or super().lookup_allowed(lookup, value, request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
