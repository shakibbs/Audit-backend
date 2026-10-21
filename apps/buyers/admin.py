"""Admin (Module 15): insurers and acquirers are invited by the clients themselves (owner decision 2026-10-22). CiV
staff see each buyer, its people and which companies share with it, and can block a buyer or a person (e.g. a fake
insurer) — they never create them."""
from django.contrib import admin
from django.utils import timezone
from unfold.admin import TabularInline

from apps.admin_panel.base import CivModelAdmin

from .models import BuyerLink, BuyerOrg, BuyerUser


class LinkInline(TabularInline):
    model = BuyerLink
    extra = 0
    fields = ('client', 'granted_by', 'granted_at', 'ends_on', 'revoked_at')
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class UserInline(TabularInline):
    model = BuyerUser
    extra = 0
    fields = ('name', 'email', 'last_login', 'is_active')
    readonly_fields = ('name', 'email', 'last_login')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(BuyerOrg)
class BuyerOrgAdmin(CivModelAdmin):
    eyebrow = 'Insurers'
    page_sub = ('Insurers and acquirers invited by clients from their own Settings (one per email domain). Untick "active" to '
                'block a buyer: its people lose access at once.')
    list_display = ('name', 'domain', 'kind', 'is_active', 'users_count', 'sharing')
    list_filter = ('kind', 'is_active')
    search_fields = ('name', 'domain')
    fields = ('name', 'domain', 'kind', 'is_active', 'created_at')
    readonly_fields = ('name', 'domain', 'kind', 'created_at')
    inlines = [UserInline, LinkInline]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='People')
    def users_count(self, org):
        return org.users.filter(is_active=True).count()

    @admin.display(description='Companies sharing')
    def sharing(self, org):
        return sum(link.active(timezone.localdate()) for link in org.links.all())
