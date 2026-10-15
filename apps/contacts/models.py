"""One call or text, in the same shape whatever tool it came from (spec: contact_event). Never the number, a name or
the message text: the person is a phone code, the text only a fingerprint in the ledger."""
from django.db import models


class ContactEvent(models.Model):
    class Channel(models.TextChoices):
        CALL = 'call', 'Call'
        TEXT = 'text', 'Text'

    class Direction(models.TextChoices):
        OUTBOUND = 'outbound', 'Outbound'
        INBOUND = 'inbound', 'Inbound'
        UNKNOWN = 'unknown', 'Unknown'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='contacts')
    phone_token = models.CharField(max_length=64, db_index=True)  # the person contacted (or who contacted the client)
    phone_token_kid = models.CharField(max_length=16)
    # Owner decision D31: shown as a masked label, area code + last 4 only ("(916) •••-0001"); the middle digits are
    # never kept, so the number cannot be rebuilt.
    masked_label = models.CharField(max_length=24, blank=True)
    source_system = models.CharField(max_length=30)
    source_record_id = models.CharField(max_length=200)
    source_grade = models.CharField(max_length=1)
    channel = models.CharField(max_length=4, choices=Channel.choices)
    direction = models.CharField(max_length=8, choices=Direction.choices)
    occurred_at = models.DateTimeField(db_index=True)  # UTC
    ended_at = models.DateTimeField(null=True, blank=True)
    answered = models.BooleanField(null=True)  # None = the tool does not say
    length_seconds = models.PositiveIntegerField(null=True, blank=True)
    disposition = models.CharField(max_length=120, blank=True)  # the tool's own result code, kept as is (AI judges stops)
    sms_status = models.CharField(max_length=30, blank=True)
    campaign = models.CharField(max_length=200, blank=True)
    agent_id = models.CharField(max_length=120, blank=True)
    caller_id_token = models.CharField(max_length=64, blank=True)  # the number shown to the person, as a phone code
    lead_id = models.CharField(max_length=120, blank=True)  # the tool's lead ID, to join lead and consent later
    # Not known from most tools yet: left empty ("unknown"), never guessed and never treated as worst case.
    dial_mode = models.CharField(max_length=30, blank=True)
    prerecorded_or_ai = models.BooleanField(null=True)
    stir_attestation = models.CharField(max_length=1, blank=True)
    is_test = models.BooleanField(default=False)  # CiV's own test numbers (Module 9)
    # Where the person probably is (location.py). Several time zones = unsure: checks use the strictest.
    recipient_state = models.CharField(max_length=2, blank=True)
    time_zones = models.JSONField(default=list, blank=True)
    country = models.CharField(max_length=2, blank=True)
    is_non_us = models.BooleanField(default=False)
    location_confidence = models.CharField(max_length=6, blank=True)  # high (ZIP, later) · medium · low
    location_source = models.CharField(max_length=12, blank=True)  # area_code (zip later)
    # The same call or text recorded by two tools (dedupe.py): one group, counted once through its main record.
    dedupe_group = models.UUIDField(null=True, blank=True, db_index=True)  # empty = not a copy of anything
    is_primary = models.BooleanField(default=True)  # count only these
    epoch = models.ForeignKey('contacts.PhoneEpoch', on_delete=models.SET_NULL, null=True, blank=True, related_name='contacts')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'contact_event'
        constraints = [models.UniqueConstraint(fields=['client', 'source_system', 'source_record_id'], name='one_contact_per_source_record')]
        indexes = [models.Index(fields=['client', 'occurred_at']), models.Index(fields=['client', 'phone_token', 'occurred_at'])]
        ordering = ['-occurred_at']

    def local_times(self):
        """The contact's time in each possible time zone of the person (empty when unknown)."""
        from zoneinfo import ZoneInfo
        return [self.occurred_at.astimezone(ZoneInfo(zone)) for zone in self.time_zones]

    def __str__(self) -> str:
        return f'{self.get_channel_display()} {self.get_direction_display().lower()} · {self.source_system} · {self.occurred_at:%Y-%m-%d %H:%M}'


class PhoneEpoch(models.Model):
    """One owner's time with a number (spec: phone epochs). Consent from one epoch never covers another."""
    class Reason(models.TextChoices):
        FIRST_SEEN = 'first_seen', 'First time CiV saw the number'
        CRM_MOVED = 'crm_moved', 'The number moved to another customer record in the CRM'
        WRONG_NUMBER = 'wrong_number', 'The person said "wrong number"'
        RND = 'rnd', 'Reassigned-number check: owner changed'
        NEW_CONSENT = 'new_consent', 'New consent from a different person'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='phone_epochs')
    phone_token = models.CharField(max_length=64)
    number = models.PositiveIntegerField()  # 1, 2, 3… in time order
    started_at = models.DateTimeField(null=True, blank=True)  # empty = from before anything CiV saw
    ended_at = models.DateTimeField(null=True, blank=True)  # empty = still the owner
    reason = models.CharField(max_length=20, choices=Reason.choices)
    signal_source = models.CharField(max_length=60, blank=True)  # e.g. hubspot, ai_review, client_rnd
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'phone_epoch'
        ordering = ['phone_token', 'number']
        constraints = [models.UniqueConstraint(fields=['client', 'phone_token', 'number'], name='epoch_number_unique')]
        indexes = [models.Index(fields=['client', 'phone_token'])]

    def __str__(self) -> str:
        return f'Epoch {self.number} · {self.started_at or "start"} → {self.ended_at or "now"} · {self.get_reason_display()}'


class CrmPhoneHolder(models.Model):
    """Which CRM record held a number, and when (record IDs only, never names). Used to see a number MOVE between
    customer records; a number on two records at once is a duplicate, not a new owner."""
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='crm_phone_holders')
    source_system = models.CharField(max_length=30)
    record_id = models.CharField(max_length=200)
    phone_token = models.CharField(max_length=64)
    held_from = models.DateTimeField()
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'crm_phone_holder'
        indexes = [models.Index(fields=['client', 'phone_token']), models.Index(fields=['client', 'source_system', 'record_id'])]
