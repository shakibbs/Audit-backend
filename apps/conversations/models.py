"""AI conversation review (spec §8, owner decision D37): each conversation where the customer spoke is read once (and
again when new messages arrive) and the AI decides whether the person still wants contact. Only the result is kept:
never the words, never the number."""
from django.db import models


class ConversationReview(models.Model):
    class Result(models.TextChoices):
        OPTED_OUT = 'opted_out', 'Asked to stop'
        PARTIAL = 'partial_request', 'Asked for a limit (time, channel, person)'
        WRONG_NUMBER = 'wrong_number', 'Wrong number'
        OPTED_BACK_IN = 'opted_back_in', 'Allowed contact again'
        UNCLEAR = 'unclear', 'Unclear'
        NONE = 'none', 'Nothing found'
        NOT_REVIEWED = 'not_reviewed', 'Not reviewed'  # the tool cannot share the words, or no AI chosen yet

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='conversation_reviews')
    phone_token = models.CharField(max_length=64, db_index=True)
    channel = models.CharField(max_length=6)  # text or call
    source_system = models.CharField(max_length=30)
    thread_end = models.ForeignKey('contacts.ContactEvent', on_delete=models.SET_NULL, null=True, related_name='+')  # last message read
    thread_end_at = models.DateTimeField()
    messages_read = models.PositiveIntegerField(default=0)
    result = models.CharField(max_length=16, choices=Result.choices)
    moment = models.ForeignKey('contacts.ContactEvent', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')  # the message that decided
    moment_at = models.DateTimeField(null=True, blank=True)
    moment_seconds = models.FloatField(null=True, blank=True)  # calls: how far into the call the deciding words came
    confidence = models.FloatField(null=True, blank=True)
    model = models.CharField(max_length=60, blank=True)  # which AI answered
    prompt_version = models.CharField(max_length=20, blank=True)
    thread_sha256 = models.CharField(max_length=64, blank=True)  # fingerprint of the words read, then dropped
    note = models.CharField(max_length=200, blank=True)  # e.g. why not reviewed
    # M45: when the customer named a lawyer ("talk to my attorney"), asked in the same AI request (no extra cost).
    attorney_at = models.DateTimeField(null=True, blank=True)
    # Module 16: the customer gave spoken consent ("yes, you can call me"). Only a flag: the client's lawyer or an Admin
    # confirms it (owner decision); it never counts as consent on its own.
    consent_at = models.DateTimeField(null=True, blank=True)
    consent_check = models.CharField(max_length=10, blank=True, choices=[('waiting', 'Waiting'), ('confirmed', 'Confirmed'), ('rejected', 'Rejected')])
    consent_checked_by = models.CharField(max_length=120, blank=True)
    trusted = models.BooleanField(default=False)  # the AI had passed its exam for this channel when it answered (step 4)
    # Step 4: while the AI is not trusted, "allowed contact again" and the new owner after "wrong number" wait for CiV staff.
    approval = models.CharField(max_length=10, blank=True, choices=[('waiting', 'Waiting'), ('approved', 'Approved'), ('rejected', 'Rejected')])
    approved_by = models.CharField(max_length=120, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    reported_wrong = models.BooleanField(default=False)  # CiV staff found this answer wrong: the AI goes back to not trusted
    reviewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'conversation_review'
        constraints = [models.UniqueConstraint(fields=['client', 'channel', 'phone_token', 'thread_end_at'], name='one_review_per_thread_end')]
        indexes = [models.Index(fields=['client', 'result', 'reviewed_at'])]
        ordering = ['-reviewed_at']


class ExamRun(models.Model):
    """Step 4, the AI's exam (accuracy gate), CiV-wide, not per client. Pass = every stop caught (100 %) and at least
    98 % of all answers right, for one channel, one AI and one instructions version. Kept forever as the record."""
    channel = models.CharField(max_length=6)  # text or call
    model = models.CharField(max_length=60)
    prompt_version = models.CharField(max_length=20)
    ran_at = models.DateTimeField(auto_now_add=True)
    cases = models.PositiveIntegerField(default=0)
    right = models.PositiveIntegerField(default=0)
    stops = models.PositiveIntegerField(default=0)
    stops_caught = models.PositiveIntegerField(default=0)
    passed = models.BooleanField(default=False)
    mistakes = models.JSONField(default=list, blank=True)  # [{case, expected, got}] (exam words are made up, never client data)
    note = models.CharField(max_length=200, blank=True)  # e.g. "a real mistake was reported"

    class Meta:
        db_table = 'conversation_exam_run'
        ordering = ['-ran_at']


class ExamCase(models.Model):
    """An extra exam question CiV staff add (e.g. written after a real mistake). Made-up words, never client data."""
    channel = models.CharField(max_length=6, choices=[('text', 'Text'), ('call', 'Call')])
    turns = models.JSONField(help_text='[{"who": "customer" or "business", "text": "...", "at": seconds (calls)}]')
    expected = models.CharField(max_length=16, choices=[(r, r) for r in ('opted_out', 'wrong_number', 'opted_back_in', 'partial_request', 'none')])
    moment = models.PositiveIntegerField(null=True, blank=True, help_text='Which turn decides (0 = first), for stops')
    note = models.CharField(max_length=200, blank=True)
    added_by = models.CharField(max_length=120, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'conversation_exam_case'
