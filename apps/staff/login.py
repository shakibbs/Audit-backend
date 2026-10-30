"""The staff panel's sign-in form with the same lock as the portal (apps/accounts/lockout.py, owner 2026-10-30): 5 wrong
passwords for one email from one computer lock it on that computer for 15 minutes; 50 from all computers lock it
everywhere and the person gets a warning email. Every wrong try is logged."""
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.exceptions import ValidationError

from apps.access_log.recorder import record
from apps.accounts.lockout import is_locked

LOCKED = 'Too many wrong tries. Wait 15 minutes, then try again.'
FAILED = 'staff_sign_in_failed'


class StaffLoginForm(AdminAuthenticationForm):
    # Plain words (owner, 2026-10-31): emails are always small letters in CiV, so no "may be case-sensitive".
    error_messages = {**AdminAuthenticationForm.error_messages, 'invalid_login': 'Wrong email or password. Check both and try again.'}

    def clean(self):
        email = (self.cleaned_data.get('username') or '').strip().lower()
        if email and is_locked(email, FAILED, request=self.request):
            record('staff_sign_in_locked', request=self.request, actor_kind='anonymous', object=email)
            raise ValidationError(LOCKED, code='locked')
        try:
            return super().clean()
        except ValidationError:
            if email:
                record(FAILED, request=self.request, actor_kind='anonymous', object=email)
            raise
