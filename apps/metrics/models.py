"""What the client says about its lead sources on Who You Contact ("this vendor checks the national DNC list"): shown
to its insurer as a statement, never counted as done until records prove it."""
from django.db import models


class LeadSourceCheck(models.Model):
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='lead_source_checks')
    source_key = models.CharField(max_length=300)  # vendor:<name> or upload:<batch key>
    column = models.CharField(max_length=10)  # national · state · internal · reassigned
    checked = models.BooleanField(default=False)
    set_by = models.ForeignKey('accounts.ClientUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    set_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'lead_source_check'
        constraints = [models.UniqueConstraint(fields=['client', 'source_key', 'column'], name='one_mark_per_source_column')]
