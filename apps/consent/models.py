"""Proofs of permission for each number and owner (spec: consent_proof). Facts only: the kind, dates, which number
(phone code), which owner epoch, the record it came from. Never a certificate's content, a name or form text."""
from django.db import models


class ConsentProof(models.Model):
    class Kind(models.TextChoices):
        CERTIFICATE = 'certificate', 'Consent certificate (TrustedForm / Jornaya)'
        SELF_ASSERTED = 'self_asserted', 'CRM consent field only (never enough alone)'
        EBR_PURCHASE = 'ebr_purchase', 'Existing customer: purchase'
        EBR_INQUIRY = 'ebr_inquiry', 'Existing customer: inquiry'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='consent_proofs')
    phone_token = models.CharField(max_length=64, db_index=True)
    epoch = models.ForeignKey('contacts.PhoneEpoch', on_delete=models.SET_NULL, null=True, blank=True, related_name='proofs')
    kind = models.CharField(max_length=14, choices=Kind.choices)
    proof_type = models.CharField(max_length=30)  # the Rulebook's word for it: web_cert, crm_flag, purchase, inquiry
    certificate = models.ForeignKey('certificates.CertificateClaim', on_delete=models.SET_NULL, null=True, blank=True, related_name='proofs')
    captured_at = models.DateTimeField(null=True, blank=True)  # when consent was given; a certificate's date comes from its claim
    date_known = models.BooleanField(default=True)  # False = the record's time stands in until the certificate is read
    source_system = models.CharField(max_length=30)
    source_record_id = models.CharField(max_length=200)
    lead_id = models.CharField(max_length=120, blank=True)  # links the proof to contacts carrying the same lead (timing rule)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'consent_proof'
        constraints = [models.UniqueConstraint(fields=['client', 'source_system', 'source_record_id', 'phone_token', 'kind', 'certificate'],
                                               name='one_proof_per_record', nulls_distinct=False)]
        indexes = [models.Index(fields=['client', 'phone_token'])]

    def when(self):
        """The best known consent time: the certificate's own creation time once claimed, else the stored time."""
        if self.certificate_id and self.certificate.cert_created_at:
            return self.certificate.cert_created_at
        return self.captured_at

    def __str__(self) -> str:
        return f'{self.get_kind_display()} · {self.when() or "date unknown"}'


class ConsentNeed(models.Model):
    """What proof one call or text needs (spec §5 "before the checks"), worked out with the rules in force on its date.
    One row per contact and variant: while a rule is undecided, strict and lenient are both kept; the portal shows strict."""
    class Variant(models.TextChoices):
        STRICT = 'strict', 'Strict'
        LENIENT = 'lenient', 'Lenient'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='consent_needs')
    contact = models.ForeignKey('contacts.ContactEvent', on_delete=models.CASCADE, related_name='consent_needs')
    variant = models.CharField(max_length=7, choices=Variant.choices)
    category = models.CharField(max_length=13)  # marketing (every campaign, strictest) / informational
    robocall = models.BooleanField()  # autodialed, prerecorded or AI voice, or a marketing text counted as autodialed
    bases = models.JSONField(default=list)  # [{basis, needs: [proof types] or ['any']}]
    labels = models.JSONField(default=list)  # e.g. category_unknown, dial_mode_unknown, dnc_list_not_supplied
    is_legal_basis = models.BooleanField()  # a basis other than civ_policy / dnc_unknown applies
    rulebook_version = models.CharField(max_length=20)
    evaluated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'consent_need'
        constraints = [models.UniqueConstraint(fields=['contact', 'variant'], name='one_need_per_contact_variant')]
