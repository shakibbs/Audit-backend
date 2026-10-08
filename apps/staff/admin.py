"""Staff section of the CiV admin panel."""
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from apps.admin_panel.base import CivModelAdmin
from apps.staff.models import StaffUser

admin.site.index_title = 'Dashboard'


class StaffCreationForm(UserCreationForm):
    class Meta:
        model = StaffUser
        fields = ('email', 'name')


class StaffChangeForm(UserChangeForm):
    class Meta:
        model = StaffUser
        fields = '__all__'


@admin.register(StaffUser)
class StaffUserAdmin(UserAdmin, CivModelAdmin):
    eyebrow = 'CiV team'
    page_sub = 'Our own team. These accounts open this panel only, never the client portal.'
    add_form = StaffCreationForm
    form = StaffChangeForm
    change_password_form = AdminPasswordChangeForm
    ordering = ('email',)
    list_display = ('email', 'name', 'is_active', 'is_superuser', 'last_login')
    list_filter = ('is_active', 'is_superuser')
    search_fields = ('email', 'name')
    readonly_fields = ('last_login', 'created_at')
    fieldsets = (
        (None, {'fields': ('email', 'name', 'password')}),
        ('Access', {'fields': ('is_active', 'is_superuser', 'groups', 'user_permissions')}),
        ('History', {'fields': ('last_login', 'created_at')}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',), 'fields': ('email', 'name', 'password1', 'password2')}),
    )


# Permission groups (e.g. "Can approve rules") shown in the same style.
admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, CivModelAdmin):
    eyebrow = 'CiV team'
    page_sub = 'Sets of permissions, for example who may approve rule changes.'
