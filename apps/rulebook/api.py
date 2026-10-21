"""Client API: the Rulebook page and its Calendar & hours tab."""
from datetime import date

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsClientUser

from .business_days import named_holidays
from .lookup import NoRulebook, RuleSet, current_version
from .models import RuleValue

# Spec key names that contain words clients may never see are shown under a plain name.
SHOWN_KEY = {'direct_violation_grade': 'direct_contact_cap_grade'}
NOTE = 'Some rules are not yet confirmed by a lawyer. Proposed values run and results are marked provisional; TBD rules are never scored.'


def in_force_today(version) -> list[RuleValue]:
    today = timezone.localdate()
    rows = RuleValue.objects.filter(version=version).order_by('key', 'jurisdiction', 'effective_from')
    return [r for r in rows if (r.effective_from is None or r.effective_from <= today) and (r.effective_to is None or today <= r.effective_to)]


class RulebookView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        try:
            version = current_version('internal')
        except NoRulebook:
            return Response({'detail': 'No rulebook yet.'}, status=404)
        rows = in_force_today(version)
        federal = [r for r in rows if r.jurisdiction == 'US']
        count = {s: sum(1 for r in federal if r.status == s) for s in ('set', 'proposed', 'tbd')}
        settings = [{'key': SHOWN_KEY.get(r.key, r.key), 'place': 'Federal' if r.jurisdiction == 'US' else r.jurisdiction,
                     'section': r.section, 'meaning': r.meaning, 'value': r.shown, 'owner': r.owner, 'status': r.status,
                     'counselItem': r.counsel_item or None, 'since': r.effective_from} for r in rows]
        return Response({'version': f'Rulebook v{version.version}', 'versionStatus': version.status,
                         'note': NOTE if version.status != 'approved' else None, **count, 'settings': settings, 'impact': []})


def hours_text(value) -> str:
    def h(t: str) -> str:
        hour, minute = (int(x) for x in t.split(':'))
        return f'{hour % 12 or 12}{":" + str(minute).zfill(2) if minute else ""}{"am" if hour < 12 else "pm"}'
    text = f'{h(value["start"])} – {h(value["end"])}'
    return text + (f'; Sunday from {h(value["sunday_start"])}' if value.get('sunday_start') else '')


def limit_text(value) -> str:
    return f'{value["max"]} per {value["window_hours"]} hours per {value["per"]}' + (', solicitations only' if value.get('applies_to') == 'solicitations' else '')


class CalendarView(APIView):
    """Calendar & hours: holidays, calling hours and limits by state, opt-out timing, how the time zone is chosen.
    A TBD value is shown as its draft value, labeled as not set yet."""
    permission_classes = [IsClientUser]

    def get(self, request):
        today = timezone.localdate()
        year = int(request.query_params.get('year') or today.year)
        if not 2000 <= year <= 2100:
            return Response({'detail': 'Year out of range.'}, status=400)
        draft = RuleSet('draft')
        live = RuleSet('internal', version=draft.version)
        holidays = [{'date': d, 'name': name, 'actual': actual} for d, name, actual in named_holidays(year)]
        upcoming = [h for y in (today.year, today.year + 1) for h in named_holidays(y) if h[0] >= today]

        def by_place(key, fmt):
            places = sorted(set(RuleValue.objects.filter(version=draft.version, key=key).values_list('jurisdiction', flat=True)),
                            key=lambda p: (p != 'US', p))
            out = []
            for place in places:
                rule = draft.get(key, on=today, state=place)
                out.append({'place': 'Federal' if place == 'US' else place, 'value': fmt(rule.value) if rule.value else None,
                            'status': rule.status, 'counselItem': rule.counsel_item or None})
            return out

        def one(key):
            rule = live.get(key, on=today)
            return {'value': rule.value, 'shown': rule.shown, 'status': rule.status, 'counselItem': rule.counsel_item or None}

        return Response({
            'year': year, 'holidays': holidays,
            'nextHoliday': {'date': upcoming[0][0], 'name': upcoming[0][1]} if upcoming else None,
            'businessDays': one('business_day_calendar') | {'shown': 'Monday to Friday, except US federal holidays, in the time zone of the person contacted'},
            'callingHours': by_place('calling_hours', hours_text),
            'smsFollowsCallingHours': one('quiet_hours_apply_to_sms'),
            'frequencyLimits': by_place('frequency_limits', limit_text),
            'restrictedHolidays': one('state_holiday_restrictions'),
            'optOut': {'deadlineDays': one('optout_deadline_business_days'), 'confirmationMinutes': one('confirmation_window_minutes'),
                       'keywords': one('optout_keywords')},
            'timeZone': {'order': ['ZIP code of the person contacted', 'Area code of the number', 'New York time (the earliest deadline)'],
                         'status': one('business_day_tz_fallback')['status']},
        })


class SnapshotView(APIView):
    """GET ?period=YYYY-MM: the Rulebook snapshot PDF for that month."""
    permission_classes = [IsClientUser]

    def get(self, request):
        import re

        from django.http import HttpResponse

        from .snapshot import snapshot_pdf
        period = request.query_params.get('period', '')
        if not re.fullmatch(r'\d{4}-\d{2}', period):
            from django.utils import timezone
            period = timezone.localdate().strftime('%Y-%m')
        response = HttpResponse(snapshot_pdf(request.user.client.name, period), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="rulebook-snapshot-{period}.pdf"'
        return response
