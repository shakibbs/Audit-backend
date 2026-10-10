"""The "Contract & billing" tab on a client company's page."""
from django.contrib import admin
from unfold.admin import StackedInline

from apps.access_log.recorder import record
from apps.billing.models import Contract


class ContractInline(StackedInline):
    model = Contract
    tab = True
    extra = 1  # an empty contract form is ready on every client
    max_num = 1
    can_delete = False
    verbose_name = 'Contract & billing'  # one contract per client, so the tab uses this name
    verbose_name_plural = 'Contract & billing'
    fieldsets = (
        ('Price', {'fields': (('price', 'currency'), ('billing_period', 'payment_method'))}),
        ('Dates', {'fields': (('contract_start', 'renewal_date'), ('auto_renew', 'notice_days'))}),
        ('Billing contact', {'fields': ('billing_contact_name', 'billing_contact_email', 'billing_contact_phone')}),
        ('Notes', {'fields': ('notes',)}),
    )


def save_contract(request, formset) -> None:
    """Saves the tab and logs which fields changed (names only, not values)."""
    for form in formset.forms:
        if not form.has_changed():
            continue
        created = form.instance.pk is None
        contract = form.save()
        fields = ', '.join(form.fields[name].label or name for name in form.changed_data if name in form.fields)
        record('contract_added' if created else 'contract_changed', request=request, actor_kind='staff',
               actor_id=request.user.pk, actor_label=request.user.email, client_id=contract.client_id, object=fields)
    formset.save(commit=False)  # sets the lists the admin's change message reads
