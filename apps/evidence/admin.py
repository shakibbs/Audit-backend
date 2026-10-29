"""Staff panel: a client's legal holds, as a tab on its page (owner, 2026-10-30). Read only: only the client's Admin or
lawyer places or releases a hold, in the portal (Evidence Vault)."""
from django.contrib import admin
from unfold.admin import TabularInline

from .models import LegalHold


class LegalHoldInline(TabularInline):
    model = LegalHold
    tab = True
    extra = 0
    can_delete = False
    verbose_name = 'legal hold'
    verbose_name_plural = 'Legal holds'
    fields = ('hold_on', 'target', 'reason', 'set_by', 'set_at', 'state')
    readonly_fields = fields
    ordering = ('released_at', '-set_at')  # active ones first

    @admin.display(description='Hold on')
    def hold_on(self, hold):
        return hold.get_scope_display()

    @admin.display(description='Status')
    def state(self, hold):
        return f'Released {hold.released_at:%d %b %Y} by {hold.released_by}' if hold.released_at else 'Active: its files are kept'

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
