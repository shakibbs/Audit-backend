"""The staff panel's sign-in form with the same lock as the portal (owner decision 2026-10-23): 5 wrong passwords for
one email within 15 minutes lock that email for 15 minutes, even with the right password. Every wrong try is logged."""
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.exceptions import ValidationError

from apps.access_log.recorder import record
from apps.accounts.lockout import is_locked

LOCKED = 'Too many wrong tries. Wait 15 minutes, then try again.'
FAILED = 'staff_sign_in_failed'


class StaffLoginForm(AdminAuthenticationForm):
    def clean(self):
        email = (self.cleaned_data.get('username') or '').strip().lower()
        if email and is_locked(email, FAILED):
            record('staff_sign_in_locked', request=self.request, actor_kind='anonymous', object=email)
            raise ValidationError(LOCKED, code='locked')
        try:
            return super().clean()
        except ValidationError:
            if email:
                record(FAILED, request=self.request, actor_kind='anonymous', object=email)
            raise
