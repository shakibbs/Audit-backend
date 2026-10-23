"""Client users (the portal's people) and invites. Kept apart from CiV staff accounts."""
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models

from apps.accounts.managers import ClientUserManager
from apps.clients.models import Client
from .fields import LowerEmailField


class Role(models.TextChoices):
    ADMIN = 'admin', 'Admin'
    MEMBER = 'member', 'Member'


class ClientUser(AbstractBaseUser):
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='users')
    email = LowerEmailField(unique=True)
    name = models.CharField(max_length=150)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    # Marks the client's lawyer: only lawyers review rule drafts and suggest law changes; lawyers and Admins sign
    # statements, decide findings, upload and export evidence (owner, 2026-10-22). Every user sees every page.
    is_counsel = models.BooleanField('is our lawyer', default=False)
    # Owner decision 2026-10-22: each person's own "View as" choice; Underwriter shows their own company as their insurer sees it.
    view = models.CharField(max_length=12, choices=[('owner', 'Owner'), ('underwriter', 'Underwriter')], default='owner')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ClientUserManager()

    USERNAME_FIELD = 'email'
    EMAIL_FIELD = 'email'

    class Meta:
        db_table = 'client_user'
        ordering = ['client__name', 'name']

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    def __str__(self):
        return f'{self.name} <{self.email}>'


class Invite(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='invites')
    email = LowerEmailField()
    name = models.CharField(max_length=150)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    is_counsel = models.BooleanField('is our lawyer', default=False)
    invited_by = models.ForeignKey(ClientUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    # Only a hash of the link's token is kept; the token itself is in the email alone.
    token_hash = models.CharField(max_length=64, unique=True)
    sent_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'client_invite'
        ordering = ['-sent_at']

    def __str__(self):
        return f'{self.email} → {self.client}'
