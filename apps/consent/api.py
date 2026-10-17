"""Client API: the Consent Integrity page (this month's summary, strict results) and the client's certificates.
Pending and frozen results are counted apart and left out of every share."""
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsClientUser
from apps.certificates.models import CertificateClaim

from .models import ConsentResult
from .words import REASONS

MIX = ['VERIFIED', 'WEAK', 'CONFLICTING', 'NO_PROOF']
NOTES = {'VERIFIED': 'All checks CiV can run passed', 'WEAK': 'Proof with a fixable gap', 'CONFLICTING': 'Sources disagree about the proof',
         'NO_PROOF': 'No accepted proof for the contact'}
HORIZONS = [('7 days', 7), ('30 days', 30), ('90 days', 90)]


def month_start(day):
    return day.replace(day=1)


def _pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def summary(client, today=None) -> dict:
    today = today or timezone.localdate()
    start = month_start(today)
    strict = ConsentResult.objects.filter(client=client, variant='strict', contact__is_primary=True)
    month = strict.filter(contact__occurred_at__date__gte=start)
    counted = month.filter(frozen=False).exclude(status__in=['pending', 'not_needed'])
    total = counted.count()
    by_status = dict(counted.values_list('status').annotate(n=Count('id')))
    mix = [{'status': s, 'count': by_status.get(s.lower(), 0), 'share': _pct(by_status.get(s.lower(), 0), total), 'note': NOTES[s]} for s in MIX]
    reasons = (counted.exclude(primary_code='VF_OK').values('primary_code').annotate(n=Count('id')).order_by('-n')[:8])
    legal = counted.filter(is_legal_basis=True).count()
    dnc_unknown = counted.filter(bases__contains=[{'basis': 'dnc_unknown'}]).count()
    with_cert = counted.filter(proof__certificate__isnull=False)  # contact–certificate pairs
    cert_pairs = with_cert.count()
    cert_bad = with_cert.filter(primary_code__startswith='CF_').count()
    firsts = [start]
    for _ in range(3):
        firsts.insert(0, month_start(firsts[0] - timedelta(days=1)))
    trend = []
    for first in firsts:
        last = month_start(first + timedelta(days=32)) - timedelta(days=1)
        rows = strict.filter(frozen=False, contact__occurred_at__date__gte=first, contact__occurred_at__date__lte=last).exclude(status__in=['pending', 'not_needed'])
        n = rows.count()
        got = dict(rows.values_list('status').annotate(c=Count('id')))
        trend.append({'label': first.strftime('%b'), **{k: round(_pct(got.get(s, 0), n)) for k, s in
                      (('verified', 'verified'), ('weak', 'weak'), ('conflicting', 'conflicting'), ('noProof', 'no_proof'))}})
    now = timezone.now()
    claims = CertificateClaim.objects.filter(client=client, state='claimed', cert_expires_at__gte=now)
    return {
        'contacts': total, 'mix': mix,
        'reasons': [{'code': r['primary_code'], 'count': r['n'], 'text': REASONS.get(r['primary_code'], r['primary_code'])} for r in reasons],
        'legalShare': round(_pct(legal, total)), 'legalCount': legal, 'policyCount': total - legal,
        'dncUnknownShare': round(_pct(dnc_unknown, total)),
        'certificateValidity': round(_pct(cert_pairs - cert_bad, cert_pairs)) if cert_pairs else 0, 'certificatePairs': cert_pairs,
        'expiredBeforeEngagement': counted.filter(labels__contains=['pre_engagement']).count(),
        'trend': trend,
        'expiring': [{'within': label, 'count': claims.filter(cert_expires_at__lte=now + timedelta(days=days)).count()} for label, days in HORIZONS],
        'pending': month.filter(status='pending', frozen=False).count(), 'frozen': month.filter(frozen=True).count(),
        'notNeeded': month.filter(status='not_needed').count(), 'period': start.strftime('%B %Y'), 'real': True,
    }


class ConsentView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        return Response(summary(request.user.client))


class CertificatesView(APIView):
    """The client's consent certificates CiV found: state, dates, and how many contacts' results used each."""
    permission_classes = [IsClientUser]

    def get(self, request):
        client = request.user.client
        claims = (CertificateClaim.objects.filter(client=client).order_by('-seen_at')
                  .annotate(used=Count('proofs__results', filter=Q(proofs__results__variant='strict'), distinct=True))[:200])
        return Response([{
            'id': f'cc-{c.pk}', 'provider': c.get_provider_display(), 'ref': f'{c.cert_ref[:8]}…', 'state': c.state, 'stateLabel': c.get_state_display(),
            'seenAt': c.seen_at, 'deadlineAt': c.deadline_at, 'createdAt': c.cert_created_at, 'expiresAt': c.cert_expires_at, 'page': c.page,
            'usedBy': c.used, 'problem': c.last_error if c.state == 'lost' else ''} for c in claims])
