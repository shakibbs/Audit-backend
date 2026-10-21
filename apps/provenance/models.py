"""Where each contacted number came from (spec §5a provenance ladder): one row per number and owner, from the latest
lead record before the first outbound contact. Names of vendors and websites only, never a person's details."""
import uuid
from pathlib import Path

from django.db import models


class Provenance(models.Model):
    class Basis(models.TextChoices):
        FEED = 'feed', 'Lead platform feed'  # rung 1: needs a lead-platform reader (none yet: on demand)
        CRM_FIELD = 'crm_field', 'CRM lead source'
        INVOICE = 'invoice', 'Vendor invoice'  # rung 3: skipped (API only; Document AI later)
        CERT_DOMAIN = 'cert_domain', 'Certificate website'
        MANUAL_IMPORT = 'manual_import', 'Uploaded list'
        UNTRACED = 'untraced', 'Untraced'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='provenance')
    phone_token = models.CharField(max_length=64)
    epoch = models.ForeignKey('contacts.PhoneEpoch', on_delete=models.CASCADE, null=True, blank=True, related_name='provenance')
    first_contact = models.ForeignKey('contacts.ContactEvent', on_delete=models.SET_NULL, null=True, related_name='+')
    first_contact_at = models.DateTimeField()
    basis = models.CharField(max_length=14, choices=Basis.choices)
    source_name = models.CharField(max_length=300, blank=True)  # the vendor as the CRM names it, or the website
    own_website = models.BooleanField(default=False)  # cert_domain: the client's own form (Module 7 source label)
    lead_system = models.CharField(max_length=30, blank=True)  # the lead record used: tool and ID (to find it in the CRM)
    lead_record_id = models.CharField(max_length=200, blank=True)
    lead_received_at = models.DateTimeField(null=True, blank=True)
    batch = models.ForeignKey('imports.ImportBatch', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    note = models.CharField(max_length=200, blank=True)  # e.g. "arrived by an automatic feed; no vendor named"
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'provenance'
        constraints = [models.UniqueConstraint(fields=['client', 'phone_token', 'epoch'], name='one_provenance_per_owner', nulls_distinct=False)]
        indexes = [models.Index(fields=['client', 'basis', 'first_contact_at'])]


def proof_file_path(request, filename: str) -> str:
    return f'client-proofs/{request.client_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


class ProofRequest(models.Model):
    """One number from an uploaded list that CiV asks the client to prove (spec §5a proof requests). Owner decision
    2026-10-21: CiV keeps the file the client attaches, privately, so it can be read; deleted after 4 years."""
    class Answer(models.TextChoices):
        PROOF = 'proof', 'Proof attached'
        NONE = 'none', 'We have none'

    class FileType(models.TextChoices):
        SIGNED_FORM = 'signed_form', 'Signed form or contract'
        RECORDING = 'recording', 'Call recording'
        EMAIL = 'email', 'Email or message'
        OTHER = 'other', 'Other'

    class Review(models.TextChoices):
        WAITING = '', 'Not checked yet'
        VALID = 'valid', 'Valid proof'
        INVALID = 'invalid', 'Not valid'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='proof_requests')
    batch_key = models.CharField(max_length=200)  # the upload, stable across batch rebuilds: system|tool|who or list|start
    batch_label = models.CharField(max_length=200)  # e.g. "Bulk import · 1,240 records · 03 Oct 2026"
    batch_size = models.PositiveIntegerField()
    phone_token = models.CharField(max_length=64)
    masked_label = models.CharField(max_length=24, blank=True)  # area code + last 4, to show the client
    sent_at = models.DateTimeField(auto_now_add=True)
    due_at = models.DateTimeField()  # 30 days: after this an unanswered request counts as "not produced"
    answer = models.CharField(max_length=5, choices=Answer.choices, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    answered_by = models.ForeignKey('accounts.ClientUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    file = models.FileField(upload_to=proof_file_path, blank=True)  # private: no public address, opened through logged views
    file_type = models.CharField(max_length=12, choices=FileType.choices, blank=True)
    original_name = models.CharField(max_length=255, blank=True)
    file_sha256 = models.CharField(max_length=64, blank=True)
    review = models.CharField(max_length=7, choices=Review.choices, blank=True)
    consent_date = models.DateField(null=True, blank=True)  # the date the proof shows consent was given (set by the reviewer)
    review_note = models.CharField(max_length=300, blank=True)
    reviewed_by = models.CharField(max_length=254, blank=True)  # the CiV staff email
    reviewed_at = models.DateTimeField(null=True, blank=True)
    purged_at = models.DateTimeField(null=True, blank=True)  # file deleted after 4 years; fingerprint kept

    class Meta:
        db_table = 'proof_request'
        constraints = [models.UniqueConstraint(fields=['client', 'batch_key', 'phone_token'], name='one_request_per_number_per_upload')]
        ordering = ['-sent_at', 'pk']

    def __str__(self) -> str:
        return f'{self.masked_label or "number"} · {self.batch_label}'
