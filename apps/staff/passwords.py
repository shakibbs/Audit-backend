"""A password may not contain the person's email name or name: CiV staff (owner, 2026-10-31), and client and insurer
people too (2026-11-07). The tester's "qa.super.staff1" passed Django's similarity check. Dots, dashes, capitals and
added digits are ignored."""
import re

from django.core.exceptions import ValidationError


def bare(text: str) -> str:
    return re.sub(r'[^a-z]', '', (text or '').lower())


class NoOwnNameValidator:
    def validate(self, password, user=None):
        if user is None:
            return
        word = bare(password)
        email_name = bare((user.email or '').split('@')[0])
        if len(email_name) >= 3 and email_name in word:
            raise ValidationError("Your password can't contain your email name.", code='password_has_email')
        for part in re.split(r'\s+', getattr(user, 'name', '') or ''):
            if len(bare(part)) >= 3 and bare(part) in word:
                raise ValidationError("Your password can't contain your name.", code='password_has_name')

    def get_help_text(self):
        return "Your password can't contain your name or the part of your email before the @."
