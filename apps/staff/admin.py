"""Staff section of the CiV admin panel."""
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html
from django.views.decorators.http import require_POST
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from unfold.forms import AdminPasswordChangeForm, UserChangeForm

from apps.admin_panel.base import CivModelAdmin
from apps.staff.login import StaffLoginForm
from apps.staff.models import StaffUser

admin.site.index_title = 'Dashboard'
admin.site.login_form = StaffLoginForm  # 5 wrong tries lock the email for 15 minutes


class StaffCreationForm(forms.ModelForm):
    """Name and email only: the person chooses their own password from the welcome link (owner decision 2026-10-22)."""
    class Meta:
        model = StaffUser
        fields = ('email', 'name')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = user.email.strip().lower()
        user.set_unusable_password()
        user.is_superuser = True  # owner, 2026-10-23: every staff member has full access for now (per-person rights later)
        if commit:
            user.save()
        return user


class StaffChangeForm(UserChangeForm):
    class Meta:
        model = StaffUser
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop('password', None)  # no password code and no "Reset password" form (owner, 2026-10-23)


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
    readonly_fields = ('last_login', 'created_at', 'password_link')
    fieldsets = (
        (None, {'fields': ('email', 'name', 'password_link')}),
        ('Access', {'fields': ('is_active', 'is_superuser', 'user_permissions')}),
        ('History', {'fields': ('last_login', 'created_at')}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',), 'fields': ('email', 'name'),
                'description': 'They get a welcome link by email (7 days) to choose their own password. New staff have full access.'}),
    )
    actions = ['send_welcome_again']

    # Nobody types a password for someone else (owner, 2026-10-23): a button emails the person a link to choose
    # their own; Django's "set this user's password" page is switched off. Staff change their own in the account menu.
    @admin.display(description='Password')
    def password_link(self, user):
        if not user.pk:
            return '-'
        url = reverse('admin:staff_staffuser_password_link', args=[user.pk])
        return format_html('<button type="submit" class="civ-btn" formaction="{}" formnovalidate>Send password link</button>'
                           '<div class="tiny" style="margin-top:6px">Emails them a link (7 days) to choose their own password.</div>', url)

    def get_urls(self):
        return [path('<int:pk>/password-link/', self.admin_site.admin_view(require_POST(self.password_link_view)),
                     name='staff_staffuser_password_link'), *super().get_urls()]

    def password_link_view(self, request, pk):
        from apps.staff.welcome import send_welcome
        user = get_object_or_404(StaffUser, pk=pk, is_active=True)
        send_welcome(user, request)
        messages.info(request, f'Password link sent to {user.email}.')
        return redirect('admin:staff_staffuser_change', pk)

    def user_change_password(self, request, id, form_url=''):
        raise PermissionDenied  # typing another person's password is not allowed

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            from apps.staff.welcome import send_welcome
            send_welcome(obj, request)
            messages.info(request, f'Welcome link sent to {obj.email}.')

    @admin.action(description='Send a password link (welcome link to choose a new password)')
    def send_welcome_again(self, request, queryset):
        from apps.staff.welcome import send_welcome
        for user in queryset.filter(is_active=True):
            send_welcome(user, request)
        messages.info(request, f'Password link sent to {queryset.filter(is_active=True).count()} people.')


# No Permission groups page (owner, 2026-10-22): each staff member's permissions are set on their own page.
admin.site.unregister(Group)
