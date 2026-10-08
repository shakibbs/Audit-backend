"""Creates client users. A user made without a password must set one through a link."""
from django.db import models


class ClientUserManager(models.Manager):
    def create_user(self, *, client, email, name, password=None, **fields):
        user = self.model(client=client, email=email.strip().lower(), name=name, **fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user
