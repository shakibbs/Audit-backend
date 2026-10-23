"""Client users and invites sections of the admin panel."""
from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html
from django.forms.models import BaseInlineFormSet
from unfold.admin import TabularInline

from apps.admin_panel.base import CivModelAdmin
from apps.access_log.recorder import record
from apps.accounts.emails import send_reset
from apps.accounts.models import ClientUser, Invite
from apps.accounts.tokens import encode_uid, reset_tokens


@admin.register(ClientUser)
class ClientUserAdmin(CivModelAdmin):
    """A person's own page, opened from a client company's Users tab. No list in the menu."""
    eyebrow = 'Clients'
    page_sub = 'People at each client who can sign in to the portal. Passwords are set by the person, never here.'
    list_display = ('email', 'name', 'client', 'role', 'is_counsel', 'is_active', 'last_login')
    list_filter = ('role', 'is_counsel', 'is_active', 'client')
    search_fields = ('email', 'name', 'client__name')
    fields = ('client', 'email', 'name', 'role', 'is_counsel', 'is_active', 'last_login', 'created_at')
    readonly_fields = ('last_login', 'created_at')
    actions = ['send_password_link']

    def has_module_permission(self, request):
        return False  # not in the menu; people are managed on their company's page

    # Passwords are never typed here: a new user gets a link to set their own.
    def save_model(self, request, obj, form, change):
        if not change:
            obj.email = obj.email.strip().lower()
            obj.set_unusable_password()
        super().save_model(request, obj, form, change)

    @admin.action(description='Send a link to set their password')
    def send_password_link(self, request, queryset):
        for user in queryset.filter(is_active=True):
            send_password_link(request, user)  # the one shared way (also the Users tab button)


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

    def has_module_permission(self, request):
        return False  # invites show on their company's Invites tab


class ClientUserInline(TabularInline):
    """Users tab on a client company's page: add and edit the client's people here.

    New people are invited from the "Invite someone" tab; passwords are never typed in the admin panel.
    """
    model = ClientUser
    tab = True
    extra = 0
    can_delete = False  # turn someone off with "Is active" instead; their history stays

    def has_add_permission(self, request, obj=None):
        return False  # new people are invited (Invite someone tab) and choose their own password
    show_change_link = True
    verbose_name = 'user'
    verbose_name_plural = 'Users'
    fields = ('name', 'email', 'role', 'is_counsel', 'is_active', 'last_login', 'row_actions')
    readonly_fields = ('last_login', 'row_actions')

    # Posts the page's form to the action URL (no nested forms); unsaved edits on the page are not kept.
    @admin.display(description='Actions')
    def row_actions(self, user):
        if not user.pk:
            return 'Gets a password link when you click Save'
        url = reverse('admin:clients_client_user_password_link', args=[user.client_id, user.pk])
        return format_html('<button type="submit" class="civ-btn" formaction="{}" formnovalidate>Send password link</button>', url)


def save_users(request, formset) -> None:
    """Saves the Users tab: new people get an unusable password and an email link; every change is logged."""
    formset.save(commit=False)  # sets new/changed lists the admin's change message reads
    for form in formset.forms:
        if not form.has_changed():
            continue
        user = form.save(commit=False)
        created = user.pk is None
        user.email = user.email.strip().lower()
        if created:
            user.set_unusable_password()
        user.save()
        record('user_added' if created else 'user_changed', request=request, actor_kind='staff', actor_id=request.user.pk,
               actor_label=request.user.email, client_id=user.client_id, object=user.email)
        if created:
            send_password_link(request, user)


def send_password_link(request, user: ClientUser) -> None:
    send_reset(user, encode_uid(user.pk), reset_tokens.make_token(user))
    record('password_link_sent', request=request, actor_kind='staff', actor_id=request.user.pk,
           actor_label=request.user.email, client_id=user.client_id, object=user.email)
    messages.info(request, f'Password link sent to {user.email}.')


class InviteInline(TabularInline):
    """Invites tab on a client company's page: every invite, whether the person joined, and a Resend button."""
    model = Invite
    tab = True
    extra = 0
    can_delete = False
    verbose_name_plural = 'Invites'
    show_title = False  # the email is already in its own column (2026-10-23)
    fields = ('email', 'name', 'role', 'is_counsel', 'state_shown', 'sent_at', 'expires_at', 'row_actions')
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description='Status')
    def state_shown(self, invite):
        from apps.accounts.invites import state
        found = state(invite)
        color = {'Joined': 'green', 'Sent': 'amber', 'Expired': 'red'}[found]
        return format_html('<span class="civ"><span class="pill pill-{}">{}</span></span>', color, found)

    # Posts the page's form to the action URL (no nested forms), like the Users tab.
    @admin.display(description='Actions')
    def row_actions(self, invite):
        if not invite.pk or invite.used_at:
            return '-'
        url = reverse('admin:clients_client_invite_resend', args=[invite.client_id, invite.pk])
        return format_html('<button type="submit" class="civ-btn" formaction="{}" formnovalidate>Resend invitation</button>', url)


class NewInviteFormSet(BaseInlineFormSet):
    """Marks the "Invite someone" tab, so saving sends invitations instead of saving rows as they are."""


class NewInviteInline(TabularInline):
    """Invite someone tab: name, email, role and the lawyer tick box; each person gets an invitation link (7 days)."""
    model = Invite
    formset = NewInviteFormSet
    tab = True
    extra = 0
    can_delete = False
    verbose_name = 'invitation'
    verbose_name_plural = 'Invite someone'
    fields = ('name', 'email', 'role', 'is_counsel')

    def get_queryset(self, request):
        return Invite.objects.none()  # only new rows here; sent invites are on the Invites tab


def invite_by_staff(request, client, *, email: str, name: str, role: str, is_counsel: bool = False):
    """CiV staff invite a person to a client company; the invite and who sent it go into the company's log."""
    from apps.accounts.invites import invite
    try:
        made = invite(client, email=email, name=name, role=role, is_counsel=is_counsel)
    except ValueError as error:
        messages.error(request, f'{email}: {error}')
        return None
    record('invite_sent', request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
           client_id=client.pk, object=made.email)
    messages.info(request, f'Invitation sent to {made.email}.')
    return made


def save_new_invites(request, client, formset) -> None:
    formset.new_objects, formset.changed_objects, formset.deleted_objects = [], [], []  # read by the admin's change message
    for form in formset.forms:
        if form.has_changed() and form.cleaned_data and not form.cleaned_data.get('DELETE'):
            d = form.cleaned_data
            invite_by_staff(request, client, email=d['email'], name=d.get('name', ''), role=d['role'], is_counsel=d.get('is_counsel', False))
