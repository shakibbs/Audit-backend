"""A new CiV team member: the panel sends a welcome link (7 days, once); the person chooses their own password on the
welcome page and then signs in to the admin panel. Sending a new link cancels the older one."""
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.forms import SetPasswordForm
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.accounts.mailer import send
from apps.accounts.tokens import INVITE_LIFETIME, hash_invite_token, new_invite_token

from .models import StaffUser, StaffWelcome


def send_welcome(user: StaffUser, request=None) -> StaffWelcome:
    token, token_hash = new_invite_token()
    with transaction.atomic():
        user.welcomes.filter(used_at__isnull=True).delete()
        made = StaffWelcome.objects.create(user=user, token_hash=token_hash, expires_at=timezone.now() + INVITE_LIFETIME)
    base = request.build_absolute_uri('/') if request else f'{settings.ADMIN_URL}/'
    link = f"{base.rstrip('/')}{reverse('staff_welcome')}?token={token}"
    send(user.email, 'Welcome to the CiV team panel', name=user.name, heading='Welcome to the CiV team',
         lines=['You have been added to the Comply iV admin panel.',
                'Click the button to choose your own password. The link works once, for 7 days.'],
         button='Choose your password', link=link, note='Nobody at CiV will ever ask you for your password.')
    return made


def open_welcome(token: str) -> StaffWelcome | None:
    return StaffWelcome.objects.select_related('user').filter(token_hash=hash_invite_token(token), used_at__isnull=True,
                                                              expires_at__gt=timezone.now(), user__is_active=True).first()


def welcome(request):
    """The page behind the welcome link: choose a password, then sign in."""
    token = request.GET.get('token', '') or request.POST.get('token', '')
    found = open_welcome(token)
    if found is None:
        messages.error(request, 'This welcome link has expired or was already used. Ask a CiV admin for a new one.')
        return redirect('admin:login')
    form = SetPasswordForm(found.user, request.POST or None)  # applies the password rules (12+ characters)
    form.fields['new_password1'].widget = forms.PasswordInput(attrs={'autocomplete': 'new-password'})
    form.fields['new_password2'].widget = forms.PasswordInput(attrs={'autocomplete': 'new-password'})
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            form.save()
            StaffWelcome.objects.filter(pk=found.pk).update(used_at=timezone.now())
        messages.success(request, 'Your password is set. Sign in with your email and new password.')
        return redirect('admin:login')
    return render(request, 'staff/welcome.html', {'form': form, 'token': token, 'person': found.user, 'title': 'Choose your password'})
