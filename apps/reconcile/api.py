"""Client API: the insurer pages' records completeness and reconciliation table for the signed-in company (its own
"insured" page only). Other fields of that page are left out until their modules (the portal keeps its sample)."""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsClientUser
from apps.buyers.authentication import IsBuyerUser
from apps.connections.providers import PROVIDERS

from .models import PeriodIntegrity, Reconciliation

LABEL = {'calls': ('Calls in {tool} logs', 'Calls {how}'), 'texts': ('Texts in {tool} logs', 'Messages {how}'),
         'crm_records': ('Records in {tool}', 'Records {how}'), 'vendor_leads': ('Vendor leads in records', 'Leads {how}')}
HOW = {'bill': 'billed by {tool}', 'tool_total': 'counted by {tool} itself', 'volume': 'expected on working days'}
SOURCE = {'bill': 'Billing API · source grade B', 'tool_total': "Tool's own total · source grade C", 'volume': 'Plausibility (working days)'}


def rows(month) -> list[dict]:
    out = []
    for r in Reconciliation.objects.filter(client=month.client, period=month.period, measure__in=LABEL, available=True).order_by('measure', 'source_system'):
        tool = PROVIDERS[r.source_system].name if r.source_system in PROVIDERS else r.source_system
        label, against = LABEL[r.measure]
        out.append({'label': label.format(tool=tool), 'against': against.format(how=HOW.get(r.method, '').format(tool=tool)),
                    'records': f'{r.records or 0:,}', 'total': f'{r.independent_total or 0:,}', 'ratio': round(r.ratio, 2) if r.ratio is not None else None,
                    'result': 'flag' if r.flagged else 'consistent', 'source': SOURCE.get(r.method, '')})
    return out


def attestation(client) -> dict:
    """The Risk Attestation rows the records already answer, over the last 30 days (shares as 0–1). Rows CiV cannot
    measure yet are left out, so the page keeps its sample (and its worst-case notes) for them."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.consent.models import ConsentResult
    from apps.contacts.models import ContactEvent
    from apps.ledger.models import Fingerprint
    from apps.optouts.models import ReaddedNumber
    from apps.provenance.models import Provenance
    from apps.uploads.models import InternalListEntry
    since = timezone.now() - timedelta(days=30)
    contacts = ContactEvent.objects.filter(client=client, direction='outbound', is_primary=True, occurred_at__gte=since)
    total = contacts.count()
    out = {'monitoring': 'Live' if client.status == 'active' else client.get_status_display(),
           'controls': {'fingerprinted': Fingerprint.objects.filter(client=client).count()}}
    if not total:
        return out
    out['contactsPerMonth'] = total
    out['selfReported'] = False
    known = contacts.exclude(prerecorded_or_ai__isnull=True)
    if known.exists():
        out['prerecordedShare'] = round(known.filter(prerecorded_or_ai=True).count() / known.count(), 3)
    traced = Provenance.objects.filter(client=client, first_contact_at__gte=since)
    if traced.exists():
        n = traced.count()
        out['purchasedShare'] = round(traced.filter(basis__in=['crm_field', 'feed']).count() / n, 3)
        manual = traced.filter(basis='manual_import')
        out['manualImportShare'] = round(manual.count() / n, 3)
        if manual.exists():
            from apps.consent.models import ConsentProof
            proven = ConsentProof.objects.filter(client=client, phone_token__in=manual.values('phone_token'), withdrawn_at__isnull=True) \
                .exclude(kind='self_asserted').values('phone_token').distinct().count()
            out['evidenceFoundShare'] = round(proven / manual.count(), 3)
    results = ConsentResult.objects.filter(client=client, variant='strict', frozen=False, contact__in=contacts).exclude(status__in=['pending', 'not_needed'])
    if results.exists():
        out['consentProof'] = round(results.filter(status__in=['verified', 'weak']).count() / results.count(), 3)
        out['contactsAfterOptOut'] = results.filter(codes__contains=['NP_AFTER_OPT_OUT']).count()
        out['reAdded'] = ReaddedNumber.objects.filter(client=client).values('phone_token').distinct().count()
    if InternalListEntry.objects.filter(client=client).exists():
        out['internalListContacts'] = sum(1 for c in contacts.only('phone_token', 'occurred_at') if InternalListEntry.objects.filter(
            client=client, phone_token=c.phone_token, added_on__lte=c.occurred_at.date()).exists())
    return out


class OwnInsuredView(APIView):
    """A client's own page; for an insurer or acquirer, a shared company's newest snapshot (Module 15)."""
    permission_classes = [IsClientUser | IsBuyerUser]

    def get(self, request, ref: str):
        from apps.buyers.models import BuyerUser
        if isinstance(request.user, BuyerUser):
            from apps.buyers.portal import one
            return one(request, ref)
        from apps.buyers.portal import as_buyer, insured, own_sheet, previewing
        if previewing(request.user):  # its own company exactly as its insurer sees it: real data only
            return as_buyer(Response(insured(own_sheet(request.user.client))))
        from apps.scoring.portal import exposure_reading
        client = request.user.client
        out = attestation(client)
        reading = exposure_reading(client)  # Module 10: the factor map and Exposure from the saved scores
        if reading:
            out['exposure'] = {'inside': reading}
        from apps.buyers.attestation import statements
        signed = statements(client)  # Module 15: the company's signed statements, conflicts shown
        out.update({'statements': signed['statements'], 'conflicts': signed['conflicts'], 'statementRows': signed['statementRows'],
                    'signedBy': signed['signedBy'], 'asOf': signed['asOf']})
        month = PeriodIntegrity.objects.filter(client=client).first()  # latest month checked
        if month is not None:
            out['completeness'] = month.completeness
            if rows(month):
                out['reconciliation'] = rows(month)
        return Response(out)
