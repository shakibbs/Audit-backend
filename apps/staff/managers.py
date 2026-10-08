"""Creates CiV staff accounts. Email is the login; there is no username."""
from django.contrib.auth.base_user import BaseUserManager


class StaffUserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email, password, **fields):
        if not email:
            raise ValueError('Staff accounts need an email.')
        user = self.model(email=self.normalize_email(email).lower(), **fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **fields):
        fields.setdefault('is_superuser', False)
        return self._create(email, password, **fields)

    def create_superuser(self, email, password=None, **fields):
        fields['is_superuser'] = True
        return self._create(email, password, **fields)
