"""GET /api/litigation: the real parts of the insurer's Litigation Intelligence page, from WebRecon's posts — the year's
TCPA filings, the latest month's class actions, repeat plaintiffs, and class actions in that month by year. Each item
replaces its sample card by id; costs, claim types and the study stay with the sample. Nothing is sent before the
first post is read."""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsClientUser
from apps.buyers.authentication import IsBuyerUser

from .models import LitigationMonth


def page() -> dict:
    latest = LitigationMonth.objects.filter(read_ok=True).first()
    if latest is None:
        return {}
    when, year = latest.month.strftime('%b %Y'), latest.month.year
    item = {'status': 'Verified', 'source': 'WebRecon', 'url': latest.url}
    headline = []
    if latest.tcpa_ytd is not None:
        label = f'Federal TCPA filings, {year}' + ('' if latest.month.month == 12 else ' so far')
        note = f'{latest.change_ytd:+.1f}% vs the same months of {year - 1}' if latest.change_ytd is not None else f'through {when}'
        headline.append({'id': 'filings-year', 'label': label, 'value': f'{latest.tcpa_ytd:,}', 'note': note, **item})
    if latest.tcpa_class is not None:
        before = LitigationMonth.objects.filter(month=latest.month.replace(year=year - 1), read_ok=True).first()
        note = f'{100 * latest.tcpa_class / latest.tcpa:.1f}% of {latest.tcpa:,} TCPA filings' if latest.tcpa else ''
        if before and before.tcpa_class is not None:
            note += f' · vs {before.tcpa_class:,} in {before.month:%b %Y}'
        headline.append({'id': 'class-month', 'label': f'Class actions filed, {when}', 'value': f'{latest.tcpa_class:,}', 'note': note, **item})
    if latest.repeat_plaintiffs is not None:
        headline.append({'id': 'repeat-plaintiffs', 'label': 'Repeat plaintiffs', 'value': f'{latest.repeat_plaintiffs:g}%',
                         'note': f'of {when} plaintiffs had sued before (all consumer laws)', **item})
    out = {'headline': headline}
    same = list(LitigationMonth.objects.filter(month__month=latest.month.month, read_ok=True, tcpa_class__isnull=False).order_by('month'))[-4:]
    if len(same) >= 2:
        out.update(classByYear=[{'label': m.month.strftime('%b %Y'), 'count': m.tcpa_class} for m in same],
                   classMonth=latest.month.strftime('%B'),
                   classSource=f'Source: WebRecon monthly statistics, read {latest.fetched_at:%-d %b %Y}.')
    return out


class LitigationView(APIView):
    permission_classes = [IsClientUser | IsBuyerUser]  # public court figures: insurers read them too (Module 15)

    def get(self, request):
        from apps.buyers.models import BuyerUser
        from apps.buyers.portal import previewing
        if isinstance(request.user, BuyerUser) or previewing(request.user):
            from apps.buyers.portal import as_buyer
            return as_buyer(Response(page()))
        return Response(page())
