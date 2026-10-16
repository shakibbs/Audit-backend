"""The STOP list (spec: opt_out_event): who asked not to be contacted, when and how. Phone codes only; never the
number or the message text. Module 9 (AI review) adds plain-word opt-outs to the same list."""
from django.db import models


class OptOutEvent(models.Model):
    class Method(models.TextChoices):
        KEYWORD = 'keyword', 'Texted a stop word'
        CRM_FLAG = 'crm_flag', '"Do not call" ticked in the CRM'
        AI = 'ai', 'Said so in plain words (AI review)'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='optouts')
    phone_token = models.CharField(max_length=64, db_index=True)
    at = models.DateTimeField()
    channel = models.CharField(max_length=6)  # text, call, crm
    method = models.CharField(max_length=10, choices=Method.choices)
    keyword = models.CharField(max_length=20, blank=True)  # which stop word (from the Rulebook list), for keyword opt-outs
    source_system = models.CharField(max_length=30)
    source_record_id = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'opt_out_event'
        ordering = ['-at']
        constraints = [models.UniqueConstraint(fields=['client', 'source_system', 'source_record_id', 'phone_token', 'method'],
                                               name='one_optout_per_source_record')]

    def __str__(self) -> str:
        return f'{self.get_method_display()} · {self.at:%Y-%m-%d %H:%M}'


class ReaddedNumber(models.Model):
    """A number that had opted out and later came back in an uploaded list (M34). Kept even when batches are rebuilt."""
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='readded_numbers')
    phone_token = models.CharField(max_length=64)
    source_system = models.CharField(max_length=30)
    record_id = models.CharField(max_length=200)  # the CRM record that brought it back
    record_created_at = models.DateTimeField()
    opted_out_at = models.DateTimeField()
    found_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'optout_readded'
        constraints = [models.UniqueConstraint(fields=['client', 'source_system', 'record_id', 'phone_token'], name='readded_once')]
