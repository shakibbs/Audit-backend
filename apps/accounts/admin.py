"""Client users and invites sections of the admin panel."""
from django.contrib import admin

from apps.admin_panel.base import CivModelAdmin
from apps.access_log.recorder import record
from apps.accounts.emails import send_reset
from apps.accounts.models import ClientUser, Invite
from apps.accounts.tokens import encode_uid, reset_tokens


@admin.register(ClientUser)
class ClientUserAdmin(CivModelAdmin):
    eyebrow = 'Clients'
    page_sub = 'People at each client who can sign in to the portal. Passwords are set by the person, never here.'
    list_display = ('email', 'name', 'client', 'role', 'is_counsel', 'is_active', 'last_login')
    list_filter = ('role', 'is_counsel', 'is_active', 'client')
    search_fields = ('email', 'name', 'client__name')
    fields = ('client', 'email', 'name', 'role', 'is_counsel', 'is_active', 'last_login', 'created_at')
    readonly_fields = ('last_login', 'created_at')
    actions = ['send_password_link']

    # Passwords are never typed here: a new user gets a link to set their own.
    def save_model(self, request, obj, form, change):
        if not change:
            obj.email = obj.email.strip().lower()
            obj.set_unusable_password()
        super().save_model(request, obj, form, change)

    @admin.action(description='Send a link to set their password')
    def send_password_link(self, request, queryset):
        users = queryset.filter(is_active=True)
        for user in users:
            send_reset(user, encode_uid(user.pk), reset_tokens.make_token(user))
            record('password_link_sent', request=request, actor_kind='staff', actor_id=request.user.pk,
                   actor_label=request.user.email, client_id=user.client_id, object=user.email)
        self.message_user(request, f'Sent to {users.count()} user(s).')


@admin.register(Invite)
class InviteAdmin(CivModelAdmin):
    eyebrow = 'Clients'
    page_sub = 'Invites sent by client Admins. Each link works once, for 7 days.'
    list_display = ('email', 'client', 'role', 'sent_at', 'expires_at', 'used_at')
    list_filter = ('role', 'client')
    search_fields = ('email', 'client__name')
    readonly_fields = ('client', 'email', 'name', 'role', 'is_counsel', 'invited_by', 'sent_at', 'expires_at', 'used_at')
    exclude = ('token_hash',)

    def has_add_permission(self, request):
        return False
