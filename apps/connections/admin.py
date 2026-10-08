"""Connections section of the admin panel: add a client's tool, lock its key, test it."""
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from unfold.admin import TabularInline

from apps.access_log.recorder import record
from apps.admin_panel.base import CivModelAdmin
from apps.connections.emails import send_connect_request
from apps.connections.forms import ConnectionForm, key_guide
from apps.connections.models import Connection, Status
from apps.connections.testers import run_test

PILL = {
    Status.CONNECTED: 'green', Status.FAILED: 'red', Status.STALE: 'amber',
    Status.WAITING: 'teal', Status.UNTESTED: 'gray', Status.NOT_CONNECTED: 'gray',
}


def status_pill(connection: Connection) -> str:
    return format_html('<span class="civ"><span class="pill pill-{}">{}</span></span>', PILL[connection.status], connection.get_status_display())


def log(request, action: str, connection: Connection) -> None:
    record(action, request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
           client_id=connection.client_id, object=str(connection))


def test_and_store(connection: Connection) -> str:
    status, message = run_test(connection)
    connection.status, connection.last_message, connection.last_checked_at = status, message, timezone.now()
    connection.save(update_fields=['status', 'last_message', 'last_checked_at'])
    return message


@admin.register(Connection)
class ConnectionAdmin(CivModelAdmin):
    eyebrow = 'Clients'
    page_sub = "Each client's tools, connected read-only. Keys are locked when saved and never shown again."
    form = ConnectionForm
    list_display = ('tool_name', 'client', 'kind', 'status_shown', 'key_saved', 'last_checked_at', 'last_message')
    list_filter = ('status', 'kind', 'provider', 'client')
    search_fields = ('client__name', 'label', 'provider')
    readonly_fields = ('kind', 'status_shown', 'key_saved', 'last_checked_at', 'last_message', 'created_at')
    actions = ['test_connections', 'send_connect_links']

    def get_fieldsets(self, request, obj=None):
        details = (None, {'fields': ('client', 'provider', 'label')})
        guide = format_html_join('', '<li>{}</li>', ((line,) for line in key_guide()))
        keys = ('Key', {'fields': ('account', 'key', 'secret'), 'description': format_html(
            'When editing, leave the fields empty to keep the saved key.'
            '<details style="margin-top:6px"><summary style="cursor:pointer;font-weight:600">Which fields each tool needs</summary>'
            '<ul style="margin:6px 0 0 18px;list-style:disc">{}</ul></details>', guide)})
        if obj is None:
            return (details, keys)
        state = ('Status', {'fields': ('kind', 'status_shown', 'key_saved', 'last_checked_at', 'last_message', 'created_at')})
        return (details, keys, state)

    @admin.display(description='Tool', ordering='provider')
    def tool_name(self, connection):
        return f'{connection.tool.name}{f" · {connection.label}" if connection.label else ""}'

    @admin.display(description='Status', ordering='status')
    def status_shown(self, connection):
        return status_pill(connection)

    @admin.display(description='Key')
    def key_saved(self, connection):
        if connection.tool.auth == 'oauth':
            return 'Client clicks Allow'
        return 'Saved · hidden' if connection.has_credentials else 'Not saved'

    def save_model(self, request, obj, form, change):
        new = form.new_credentials()
        if new:
            obj.set_credentials({**(obj.get_credentials() if obj.has_credentials else {}), **new})
        if not change and obj.tool.auth == 'oauth':
            obj.status = Status.WAITING
        super().save_model(request, obj, form, change)
        log(request, 'connection_added' if not change else ('connection_key_changed' if new else 'connection_changed'), obj)
        if new:  # test right away, so the status is real
            messages.info(request, test_and_store(obj))
            log(request, 'connection_tested', obj)

    def delete_model(self, request, obj):
        log(request, 'connection_removed', obj)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for connection in queryset:
            log(request, 'connection_removed', connection)
        super().delete_queryset(request, queryset)

    @admin.action(description='Test connection')
    def test_connections(self, request, queryset):
        for connection in queryset:
            self.message_user(request, f'{connection}: {test_and_store(connection)}')
            log(request, 'connection_tested', connection)

    @admin.action(description='Send connect link to client Admins')
    def send_connect_links(self, request, queryset):
        for connection in queryset:
            if connection.tool.auth != 'oauth':
                self.message_user(request, f'{connection}: uses a key, not a connect link.', messages.WARNING)
                continue
            sent_to = send_connect_request(connection)
            if not sent_to:
                self.message_user(request, f'{connection.client} has no active Admin to send to.', messages.WARNING)
                continue
            connection.status = Status.WAITING
            connection.save(update_fields=['status'])
            log(request, 'connect_link_sent', connection)
            self.message_user(request, f'{connection}: sent to {", ".join(sent_to)}.')


class ConnectionInline(TabularInline):
    """Read-only list of a client's connections on the client company page."""
    model = Connection
    show_title = False
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ('tool', 'kind', 'status_shown', 'last_checked_at')
    readonly_fields = fields
    verbose_name_plural = 'Connections'

    @admin.display(description='Tool')
    def tool(self, connection):
        return connection.tool.name

    @admin.display(description='Status')
    def status_shown(self, connection):
        return status_pill(connection)

    def has_add_permission(self, request, obj=None):
        return False
