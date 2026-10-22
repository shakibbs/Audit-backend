"""CiV's own team. These accounts open the admin panel only, never the client API."""
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from apps.staff.managers import StaffUserManager


class StaffUser(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = StaffUserManager()

    USERNAME_FIELD = 'email'
    EMAIL_FIELD = 'email'
    REQUIRED_FIELDS = ['name']

    class Meta:
        db_table = 'staff_user'
        verbose_name = 'CiV staff member'
        verbose_name_plural = 'CiV staff'

    # Every staff account may open the admin panel; what it can do there comes from its permissions.
    @property
    def is_staff(self):
        return self.is_active

    def __str__(self):
        return f'{self.name} <{self.email}>'


class StaffWelcome(models.Model):
    """A new CiV team member's link to choose their own password (owner decision 2026-10-22: no password is ever typed
    for someone else). Works once, for 7 days; only a hash of the link is kept."""
    user = models.ForeignKey(StaffUser, on_delete=models.CASCADE, related_name='welcomes')
    token_hash = models.CharField(max_length=64, unique=True)
    sent_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'staff_welcome'
        ordering = ['-sent_at']
