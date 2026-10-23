"""Emails are always kept in small letters (owner, 2026-10-23): typed "QA.Admin@x.com" becomes "qa.admin@x.com" before
anything checks it, so "already has an account" is found and nothing crashes."""
from django import forms
from django.db import models


class LowerEmailFormField(forms.EmailField):
    def to_python(self, value):
        return super().to_python(value).strip().lower()


class LowerEmailField(models.EmailField):
    def to_python(self, value):
        value = super().to_python(value)
        return value.strip().lower() if isinstance(value, str) else value

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return value.strip().lower() if isinstance(value, str) else value

    def pre_save(self, model_instance, add):
        value = getattr(model_instance, self.attname)
        if isinstance(value, str):
            value = value.strip().lower()
            setattr(model_instance, self.attname, value)
        return value

    def formfield(self, **kwargs):
        return super().formfield(**{'form_class': LowerEmailFormField, **kwargs})
