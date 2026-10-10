"""What a client pays and when its contract renews. One contract per client company."""
from datetime import date, timedelta

from django.db import models

from apps.clients.models import Client


class Contract(models.Model):
    class Period(models.TextChoices):
        MONTHLY = 'monthly', 'Monthly'
        QUARTERLY = 'quarterly', 'Quarterly'
        YEARLY = 'yearly', 'Yearly'

    class Payment(models.TextChoices):
        INVOICE = 'invoice', 'Invoice'
        CARD = 'card', 'Card'
        ACH = 'ach', 'Bank transfer (ACH)'
        OTHER = 'other', 'Other'

    client = models.OneToOneField(Client, on_delete=models.CASCADE, related_name='contract')
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default='USD')
    billing_period = models.CharField(max_length=10, choices=Period.choices, default=Period.MONTHLY)
    payment_method = models.CharField(max_length=10, choices=Payment.choices, default=Payment.INVOICE)
    contract_start = models.DateField(null=True, blank=True)
    renewal_date = models.DateField('contract end / renewal date', null=True, blank=True)
    auto_renew = models.BooleanField('renews automatically', default=True)
    notice_days = models.PositiveSmallIntegerField('notice period (days)', default=30,
                                                   help_text='How many days before the renewal date either side must give notice.')
    billing_contact_name = models.CharField(max_length=150, blank=True)
    billing_contact_email = models.EmailField(blank=True)
    billing_contact_phone = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'contract'
        verbose_name = 'contract'
        verbose_name_plural = 'Contract & billing'

    def __str__(self):
        return f'Contract · {self.client}'

    @property
    def price_text(self) -> str:
        if self.price is None:
            return ''
        per = {'monthly': 'month', 'quarterly': 'quarter', 'yearly': 'year'}[self.billing_period]
        symbol = '$' if self.currency == 'USD' else f'{self.currency} '
        return f'{symbol}{self.price:,.2f} / {per}'.replace('.00 /', ' /')

    def days_to_renewal(self, today: date | None = None) -> int | None:
        return (self.renewal_date - (today or date.today())).days if self.renewal_date else None

    # Inside the notice period (or past due): time to talk to the client about renewing.
    def renews_soon(self, today: date | None = None) -> bool:
        days = self.days_to_renewal(today)
        return days is not None and days <= self.notice_days


def renewals_within(days: int, today: date | None = None):
    today = today or date.today()
    return Contract.objects.filter(renewal_date__gte=today, renewal_date__lte=today + timedelta(days=days),
                                   client__is_active=True)
