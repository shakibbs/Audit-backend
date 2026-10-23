"""GET /api/litigation: the insurer's Litigation Intelligence page. Live figures from WebRecon's posts (the year's TCPA
filings, the latest month's class actions, repeat plaintiffs, class actions in that month by year) and the fixed,
sourced reference text (costs, claim types, the docket study). Before the first post is read the live cards are absent."""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsClientUser
from apps.buyers.authentication import IsBuyerUser

from .models import LitigationMonth


SETTLEMENT = {'id': 'class-settlement', 'label': 'Average class settlement', 'value': '$6.6M', 'note': 'Defense up to $2M', 'status': 'Verified',
              'source': 'Insurance Business', 'url': 'https://www.insurancebusinessmag.com/us/news/claims/robocall-claims-on-the-up-but-many-underinsured-455359.aspx'}
COSTS = [
    {'label': 'Statutory damages', 'value': '$500 per call or text; up to $1,500 if willful or knowing; no cap in a class', 'status': 'Statute'},
    {'label': 'Individual suit', 'value': 'Typically settles in the low five figures plus defense', 'status': 'Estimate'},
    {'label': 'Class action', 'value': 'Average settlement $6.6M; defense up to $2M', 'status': 'Verified'},
    {'label': 'Insurance today', 'value': 'General liability and umbrella policies almost all exclude TCPA; a few carriers write it, mostly defense-only sublimits', 'status': 'Verified'},
]
CLAIM_TYPES = [
    {'type': 'Opt-out not honored', 'hook': '47 CFR 64.1200(a)(10)', 'direction': 'Growing: any-reasonable-means rule gives a simple fact pattern'},
    {'type': 'National DNC registry', 'hook': '64.1200(c)(2)', 'direction': 'Growing: the easiest class to certify'},
    {'type': 'Internal DNC / company list', 'hook': '64.1200(d)', 'direction': 'Growing'},
    {'type': 'Texts as calls', 'hook': '§227; state statutes (TX SB 140, FL FTSA)', 'direction': 'Growing in state court'},
    {'type': 'Prerecorded / AI voice without consent', 'hook': '§227(b)(1)(B)', 'direction': 'Steady; AI voice is new'},
    {'type': 'Autodialer', 'hook': '§227(b)(1)(A)', 'direction': 'Declining federally; McLaughlin (2025) reopens readings'},
    {'type': 'Calling hours and frequency', 'hook': '64.1200(c)(1); state windows', 'direction': 'Growing in FL, OK, WA'},
]
STUDY = [
    {'step': '1. Pull dockets', 'how': 'CourtListener RECAP API: nature-of-suit 890, cause 47:227, 2023–2026; PACER for missing complaints', 'cost': '~$8K/yr PACER · 1 week'},
    {'step': '2. Classify complaints', 'how': 'Court, date and class flag by rule; claim type, channel, industry, outcome and amount by AI with a fixed form; 100 hand-checked first', 'cost': '~$150 of AI · 2 weeks'},
    {'step': '3. Resolve defendants', 'how': 'Match each defendant to a company record so suits can be counted per 100 companies', 'cost': '2 weeks'},
    {'step': '4. Price outcomes', 'how': 'Settlement approval orders; dismissal and default rates by claim type', 'cost': '~$100–300/mo docket service'},
    {'step': '5. Publish', 'how': 'Base rates by industry, volume band and channel; cost per suit by claim type; refreshed quarterly', 'cost': 'Quarterly'},
]


def page() -> dict:
    out = {'headline': [SETTLEMENT], 'classByYear': [], 'costs': COSTS, 'claimTypes': CLAIM_TYPES, 'study': STUDY}
    latest = LitigationMonth.objects.filter(read_ok=True).first()
    if latest is None:
        return out
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
    out['headline'] = headline + [SETTLEMENT]
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
