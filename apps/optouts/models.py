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
    lifted_at = models.DateTimeField(null=True, blank=True)  # the person allowed contact again (AI review): no longer in force from then
    # False: found by the AI while it had not passed its exam (Module 9 step 4). Still on the STOP list and still checked
    # in the tools (people stay safe), but not counted against the client's score (M10, M38).
    counts = models.BooleanField(default=True)
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


class MarkCheck(models.Model):
    """Module 9 step 3: was the number marked "do not contact" in one of the client's tools after an opt-out?
    marked: True / False / None (the tool can't tell CiV: "not checked", never a fail). Not marked 15 minutes after CiV
    learned of the opt-out → urgent (shown in the portal; no email). Still not marked at the deadline → missed (M38)."""
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='mark_checks')
    optout = models.ForeignKey(OptOutEvent, on_delete=models.CASCADE, related_name='mark_checks')
    connection = models.ForeignKey('connections.Connection', on_delete=models.CASCADE, related_name='+')
    marked = models.BooleanField(null=True)
    note = models.CharField(max_length=200, blank=True)  # why not checked
    deadline_at = models.DateTimeField(null=True, blank=True)  # end of the deadline day, in the person's time zone
    first_checked_at = models.DateTimeField(auto_now_add=True)
    checked_at = models.DateTimeField()
    marked_at = models.DateTimeField(null=True, blank=True)  # first time CiV saw it marked
    urgent_at = models.DateTimeField(null=True, blank=True)  # urgent alert raised
    day_check_done = models.BooleanField(default=False)  # the one extra check a day later (marked, then unmarked?)
    missed = models.BooleanField(default=False)  # M38

    class Meta:
        db_table = 'optout_mark_check'
        constraints = [models.UniqueConstraint(fields=['optout', 'connection'], name='one_mark_check_per_tool')]
        indexes = [models.Index(fields=['client', 'missed']), models.Index(fields=['client', 'urgent_at'])]
