"""Connections inside the client company page: add a client's tools, lock their keys, test them.

There is no separate Connections page: everything happens on the client's page (ClientAdmin).
"""
from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from unfold.admin import StackedInline

from apps.access_log.recorder import record
from apps.connections.forms import ConnectionInlineForm, key_guide
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


def save_connections(request, formset) -> None:
    """Saves the Connections tab: locks new keys, logs every change, tests tools whose key changed."""
    formset.save(commit=False)  # fills formset.deleted_objects
    for connection in formset.deleted_objects:
        log(request, 'connection_removed', connection)
        connection.delete()
    for form in formset.forms:
        if form in formset.deleted_forms or not form.has_changed():
            continue
        connection = form.save(commit=False)
        created = connection.pk is None
        new = form.new_credentials()
        if new:
            connection.set_credentials({**(connection.get_credentials() if connection.has_credentials else {}), **new})
        if created and connection.tool.auth == 'oauth':
            connection.status = Status.WAITING
        connection.save()
        log(request, 'connection_added' if created else ('connection_key_changed' if new else 'connection_changed'), connection)
        if new:  # test right away, so the status is real
            messages.info(request, f'{connection.tool.name}: {test_and_store(connection)}')
            log(request, 'connection_tested', connection)


class ConnectionInline(StackedInline):
    """The Connections tab of a client company: one block per tool."""
    model = Connection
    form = ConnectionInlineForm
    tab = True
    extra = 0
    show_change_link = False
    verbose_name = 'connection'
    verbose_name_plural = 'Connections'
    fields = ('provider', 'label', 'account', 'key', 'secret', 'status_shown', 'key_saved', 'last_checked_at', 'last_message', 'row_actions')
    readonly_fields = ('status_shown', 'key_saved', 'last_checked_at', 'last_message', 'row_actions')

    @admin.display(description='Status')
    def status_shown(self, connection):
        return status_pill(connection) if connection.pk else 'Saved when you click Save'

    @admin.display(description='Saved key')
    def key_saved(self, connection):
        if not connection.pk:
            return '-'
        if connection.tool.auth == 'oauth':
            return 'No key: the client clicks Allow'
        return 'Saved · hidden (leave the fields empty to keep it)' if connection.has_credentials else 'Not saved'

    # Buttons post the page's form to the action URL (no nested forms); unsaved edits on the page are not kept.
    @admin.display(description='Actions')
    def row_actions(self, connection):
        if not connection.pk:
            return '-'
        args = [connection.client_id, connection.pk]
        if connection.tool.auth == 'oauth':
            url, label = reverse('admin:clients_client_connection_link', args=args), 'Send connect link to client Admins'
        else:
            url, label = reverse('admin:clients_client_connection_test', args=args), 'Test connection now'
        return format_html('<button type="submit" class="civ-btn" formaction="{}" formnovalidate>{}</button>', url, label)


def key_guide_html() -> str:
    guide = format_html_join('', '<li>{}</li>', ((line,) for line in key_guide()))
    return format_html('<details><summary style="cursor:pointer;font-weight:600">Which fields each tool needs</summary>'
                       '<ul style="margin:6px 0 0 18px;list-style:disc">{}</ul></details>', guide)
