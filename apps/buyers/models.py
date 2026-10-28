"""Module 15 step 1: buyers — insurers and acquirers (spec §9a). Owner decision 2026-10-22: the CLIENT invites its own
insurer (or acquirer) from its Settings, by the underwriter's email; CiV staff only see and can block. A buyer is one
company per email domain (so a client can never put a person into another company's insurer account; a free-mail
address is a buyer of its own). A buyer sees a company only while that company shares with it (`BuyerLink`); an
acquirer's sharing also ends on its date. Buyers never see contact-level records."""
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from apps.accounts.fields import LowerEmailField


class BuyerOrg(models.Model):
    class Kind(models.TextChoices):
        INSURER = 'insurer', 'Insurer'
        ACQUIRER = 'acquirer', 'Acquirer'

    name = models.CharField(max_length=150)
    domain = models.CharField(max_length=150, unique=True)  # e.g. falconrisk.com, or the full address for free mail
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.INSURER)
    is_active = models.BooleanField(default=True)  # CiV staff can block a buyer
    # "Delete" in the staff panel hides and switches the buyer off; its people, invites, sharing and rating engine are
    # kept and it can be restored (owner, 2026-10-24, same as client companies).
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)
    deleted_by = models.CharField(max_length=254, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'insurer or acquirer'
        verbose_name_plural = 'insurers and acquirers'  # same words as the staff menu (2026-10-23)
        db_table = 'buyer_org'
        ordering = ['name']

    def __str__(self) -> str:
        return f'{self.name} ({self.get_kind_display()})'


class BuyerUserManager(BaseUserManager):
    def create_user(self, email, password=None, **fields):
        user = self.model(email=self.normalize_email(email).lower(), **fields)
        user.set_password(password)
        user.save()
        return user


class BuyerUser(AbstractBaseUser):
    """An underwriter (or deal counsel) who signs into the portal and only ever sees the underwriter view."""
    org = models.ForeignKey(BuyerOrg, on_delete=models.PROTECT, related_name='users')
    email = LowerEmailField(unique=True)
    name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = BuyerUserManager()

    USERNAME_FIELD = 'email'
    EMAIL_FIELD = 'email'

    class Meta:
        db_table = 'buyer_user'
        ordering = ['org__name', 'name']

    def __str__(self) -> str:
        return f'{self.name} <{self.email}>'


class BuyerLink(models.Model):
    """A company shares its attestation, data integrity and export with one buyer, until it stops (or the end date)."""
    org = models.ForeignKey(BuyerOrg, on_delete=models.PROTECT, related_name='links')
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='buyer_links')
    granted_by = models.CharField(max_length=200)
    granted_at = models.DateTimeField(auto_now_add=True)
    ends_on = models.DateField(null=True, blank=True)  # acquirers: sharing ends on this day
    revoked_by = models.CharField(max_length=200, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'buyer_link'
        ordering = ['-granted_at']

    def active(self, today) -> bool:
        return (self.revoked_at is None and (self.ends_on is None or today <= self.ends_on)
                and self.client.deleted_at is None and self.org.deleted_at is None)  # nothing is shared with a deleted side

    def __str__(self):
        return f'{self.client} → {self.org}'


class BuyerInvite(models.Model):
    """A client's invite to a person at its insurer or acquirer who has no account yet: they set a password from the
    link (same sign-in page as client invites)."""
    org = models.ForeignKey(BuyerOrg, on_delete=models.CASCADE, related_name='invites')
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='buyer_invites')  # who invited
    email = LowerEmailField()
    name = models.CharField(max_length=150, blank=True)
    invited_by = models.CharField(max_length=200)
    token_hash = models.CharField(max_length=64, unique=True)
    sent_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'buyer_invite'

    def __str__(self):
        return f'Invite to {self.email} (from {self.client})'


class Statement(models.Model):
    """Something the company states about itself that CiV cannot measure (spec §9a "Insured states"). Signed by an
    Admin or the company's lawyer, shown to its insurer, never raises any value; CiV shows a conflict when what it
    measured says otherwise (owner decision 2026-10-22: written on the company's own Risk Attestation page)."""
    class Topic(models.TextChoices):
        DNC = 'dnc_checked', 'We check every number against the National Do Not Call Registry'
        INTERNAL = 'internal_list', 'We never contact numbers on our internal do-not-call list'
        OPTOUTS = 'optouts_honored', 'We stop contacting people who opt out'
        CONSENT = 'consent_all', 'We have consent for every marketing contact'
        OTHER = 'other', 'Something else'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='statements')
    topic = models.CharField(max_length=20, choices=Topic.choices, default=Topic.OTHER)
    text = models.CharField(max_length=500)
    signed_by = models.CharField(max_length=200)
    signed_at = models.DateTimeField(auto_now_add=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'insured_statement'
        ordering = ['signed_at']


class AttestationSnapshot(models.Model):
    """Module 15 step 2: the company's monthly risk attestation (schema civ.attestation.v1), saved with its SHA-256.
    The open month is saved again every night; a month locked 5 days after it ends is never overwritten — a change
    makes a new version (like the score snapshots)."""
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='attestations')
    period = models.DateField()
    version = models.PositiveIntegerField(default=1)
    payload = models.JSONField()
    sha256 = models.CharField(max_length=64)
    made_at = models.DateTimeField(auto_now=True)
    locked = models.BooleanField(default=False)

    class Meta:
        db_table = 'attestation_snapshot'
        constraints = [models.UniqueConstraint(fields=['client', 'period', 'version'], name='one_attestation_version')]
        ordering = ['-period', '-version']


class RatingEngine(models.Model):
    """Module 15: where an insurer's own pricing software takes CiV's monthly sheet. The insurer types its address
    and key; the key is locked like a client's tool key and never shown again (only its last 4 characters)."""
    class Adapter(models.TextChoices):
        JSON_POST = 'json_post', 'JSON over HTTPS (signed)'

    org = models.OneToOneField(BuyerOrg, on_delete=models.CASCADE, related_name='engine')
    adapter = models.CharField(max_length=20, choices=Adapter.choices, default=Adapter.JSON_POST)
    url = models.URLField(max_length=500)
    key = models.TextField(blank=True, editable=False)  # locked
    key_hint = models.CharField(max_length=4, blank=True)
    monthly = models.BooleanField(default=False)  # send each locked month on its own
    updated_by = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rating_engine'


class RatingSend(models.Model):
    """One sheet sent to an insurer's software, kept for both sides to see what went and whether it was accepted."""
    org = models.ForeignKey(BuyerOrg, on_delete=models.CASCADE, related_name='sends')
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='rating_sends')
    snapshot = models.ForeignKey(AttestationSnapshot, on_delete=models.SET_NULL, null=True, related_name='sends')
    company = models.CharField(max_length=200)
    sent_at = models.DateTimeField(auto_now_add=True)
    by = models.CharField(max_length=200)  # the person, or "Monthly send"
    ok = models.BooleanField(default=False)
    status = models.PositiveSmallIntegerField(null=True, blank=True)
    detail = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = 'rating_send'
        ordering = ['-sent_at']
