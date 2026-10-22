"""Admin (Module 15): insurers and acquirers are invited by the clients themselves (owner decision 2026-10-22). CiV
staff see each buyer, its people and which companies share with it, and can block a buyer or a person (e.g. a fake
insurer) — they never create them."""
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html
from django.views.decorators.http import require_POST
from django.utils import timezone
from unfold.admin import TabularInline

from apps.access_log.recorder import record
from apps.admin_panel.base import CivModelAdmin

from .models import BuyerInvite, BuyerLink, BuyerOrg, BuyerUser


class LinkInline(TabularInline):
    """Companies sharing with this insurer; staff can stop a share (the company sees it in its access log)."""
    model = BuyerLink
    extra = 0
    verbose_name, verbose_name_plural = 'company sharing', 'Companies sharing'
    fields = ('client', 'granted_by', 'granted_at', 'ends_on', 'state', 'row_actions')
    readonly_fields = fields
    can_delete = False

    @admin.display(description='Status')
    def state(self, link):
        if link.revoked_at:
            return f'Stopped {link.revoked_at:%-d %b %Y} by {link.revoked_by}'
        return 'Sharing' if link.active(timezone.localdate()) else 'Ended'

    @admin.display(description='Actions')
    def row_actions(self, link):
        if not link.pk or not link.active(timezone.localdate()):
            return '-'
        url = reverse('admin:buyers_buyerorg_stop_sharing', args=[link.org_id, link.pk])
        return format_html('<button type="submit" class="civ-btn" formaction="{}" formnovalidate>Stop sharing</button>', url)

    def has_add_permission(self, request, obj=None):
        return False


class UserInline(TabularInline):
    """People at this insurer who have set a password. Untick "Is active" to turn one person off."""
    model = BuyerUser
    extra = 0
    verbose_name, verbose_name_plural = 'person', 'People (joined)'
    fields = ('name', 'email', 'last_login', 'is_active', 'row_actions')
    readonly_fields = ('name', 'email', 'last_login', 'row_actions')
    can_delete = True  # tick "Delete" and Save: the person is removed for good (owner, 2026-10-22)

    # Posts the page's form to the action URL (no nested forms), like a client's Users tab.
    @admin.display(description='Actions')
    def row_actions(self, user):
        if not user.pk or not user.is_active:
            return '-'
        url = reverse('admin:buyers_buyerorg_password_link', args=[user.org_id, user.pk])
        return format_html('<button type="submit" class="civ-btn" formaction="{}" formnovalidate>Send password link</button>', url)

    def has_add_permission(self, request, obj=None):
        return False


class InviteInline(TabularInline):
    """People invited who have not set a password yet: Resend (new 7-day link) or Cancel."""
    model = BuyerInvite
    extra = 0
    verbose_name, verbose_name_plural = 'invitation', 'Waiting invitations'
    fields = ('name', 'email', 'client', 'invited_by', 'sent_at', 'state', 'row_actions')
    readonly_fields = fields
    can_delete = False

    def get_queryset(self, request):
        return super().get_queryset(request).filter(used_at__isnull=True)

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description='Status')
    def state(self, invite):
        return 'Expired' if invite.expires_at <= timezone.now() else f'Sent · link works until {invite.expires_at:%-d %b}'

    @admin.display(description='Actions')
    def row_actions(self, invite):
        if not invite.pk:
            return '-'
        resend = reverse('admin:buyers_buyerorg_invite', args=[invite.org_id, invite.pk, 'resend'])
        cancel = reverse('admin:buyers_buyerorg_invite', args=[invite.org_id, invite.pk, 'cancel'])
        return format_html('<button type="submit" class="civ-btn" formaction="{}" formnovalidate>Resend</button> '
                           '<button type="submit" class="civ-btn" formaction="{}" formnovalidate>Cancel</button>', resend, cancel)


@admin.register(BuyerOrg)
class BuyerOrgAdmin(CivModelAdmin):
    def get_urls(self):
        site = self.admin_site
        return [path('<int:org_id>/people/<int:user_id>/password-link/', site.admin_view(password_link), name='buyers_buyerorg_password_link'),
                path('<int:org_id>/invites/<int:invite_id>/<str:verb>/', site.admin_view(invite_action), name='buyers_buyerorg_invite'),
                path('<int:org_id>/links/<int:link_id>/stop/', site.admin_view(stop_sharing), name='buyers_buyerorg_stop_sharing'),
                *super().get_urls()]

    eyebrow = 'Insurers'
    page_sub = ('Insurers and acquirers invited by clients from their own Settings (one per email domain). Untick "active" to '
                'block a buyer: its people lose access at once.')
    list_display = ('name', 'domain', 'kind', 'is_active', 'users_count', 'sharing')
    list_filter = ('kind', 'is_active')
    search_fields = ('name', 'domain')
    fields = ('name', 'domain', 'kind', 'is_active', 'created_at')
    readonly_fields = ('name', 'domain', 'kind', 'created_at')
    inlines = [UserInline, InviteInline, LinkInline]

    def has_add_permission(self, request):
        return False

    def delete_model(self, request, org):
        """Deletes an insurer for good with its people, invitations, sharing and rating engine (owner, 2026-10-22).
        Each company that shared gets a line in its access log; the log keeps names as text."""
        for link in org.links.select_related('client'):
            record('buyer_deleted', request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
                   client_id=link.client_id, object=org.name)
        org.links.all().delete()
        org.users.all().delete()
        super().delete_model(request, org)

    def get_deleted_objects(self, objs, request):
        # People and sharing are protected from accidental deletion elsewhere; delete_model removes them first here.
        deleted, counts, perms, _ = super().get_deleted_objects(objs, request)
        return deleted, counts, perms, []

    def delete_queryset(self, request, queryset):
        for org in queryset:
            self.delete_model(request, org)

    def save_formset(self, request, form, formset, change):
        if formset.model is BuyerUser:
            for gone in formset.deleted_forms:
                if gone.instance.pk:
                    record('buyer_user_deleted', request=request, actor_kind='staff', actor_id=request.user.pk,
                           actor_label=request.user.email, object=f'{gone.instance.email} ({gone.instance.org.name})')
        super().save_formset(request, form, formset, change)

    @admin.display(description='People')
    def users_count(self, org):
        return org.users.filter(is_active=True).count()

    @admin.display(description='Companies sharing')
    def sharing(self, org):
        return sum(link.active(timezone.localdate()) for link in org.links.all())


@require_POST
def password_link(request, org_id, user_id):
    """CiV staff email an insurer or acquirer person a link to choose a new password (owner decision 2026-10-22)."""
    staff_only(request)
    from .invite import send_password_link
    person = get_object_or_404(BuyerUser, pk=user_id, org_id=org_id, is_active=True)
    send_password_link(person)
    record('password_link_sent', request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
           object=f'{person.email} ({person.org.name})')
    messages.info(request, f'Password link sent to {person.email}.')
    return redirect(reverse('admin:buyers_buyerorg_change', args=[org_id]))


def staff_only(request):
    if not request.user.has_perm('buyers.change_buyerorg'):
        raise PermissionDenied


def back(org_id):
    return redirect(reverse('admin:buyers_buyerorg_change', args=[org_id]))


@require_POST
def invite_action(request, org_id, invite_id, verb):
    """Resend a waiting insurer invitation (new link) or cancel it (the link stops working)."""
    staff_only(request)
    from .invite import resend
    invite = get_object_or_404(BuyerInvite, pk=invite_id, org_id=org_id, used_at__isnull=True)
    if verb == 'resend':
        resend(invite)
        messages.info(request, f'A new invitation link was sent to {invite.email}.')
    elif verb == 'cancel':
        invite.delete()
        messages.info(request, f'Invitation to {invite.email} cancelled.')
    else:
        raise PermissionDenied
    record(f'buyer_invite_{verb}', request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
           client_id=invite.client_id, object=invite.email)
    return back(org_id)


@require_POST
def stop_sharing(request, org_id, link_id):
    """CiV staff stop one company's sharing with this insurer; it ends at the insurer's next click."""
    staff_only(request)
    link = get_object_or_404(BuyerLink, pk=link_id, org_id=org_id, revoked_at__isnull=True)
    link.revoked_by, link.revoked_at = f'CiV ({request.user.email})', timezone.now()
    link.save(update_fields=['revoked_by', 'revoked_at'])
    record('buyer_link_revoked', request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
           client_id=link.client_id, object=link.org.name)
    messages.info(request, f'{link.client.name} no longer shares with {link.org.name}.')
    return back(org_id)
