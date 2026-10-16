"""Client API: the Opt-outs card on Revocation Integrity. Every opt-out on the STOP list, newest first, with its
deadline (business days, in the person's time zone) and any contact after it. Whether the dialer marked the number
is checked in Module 9: until then "not checked yet"."""
from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsClientUser
from apps.contacts.api import number_ref
from apps.contacts.models import ContactEvent
from apps.rulebook.business_days import BusinessCalendar, optout_deadline, pick_time_zone
from apps.rulebook.lookup import NoRulebook, RuleSet

from .models import OptOutEvent

LIMIT = 200
HOW = {('keyword', 'text'): 'Text · keyword', ('crm_flag', 'crm'): 'CRM · do not call', ('ai', 'call'): 'Call · AI review', ('ai', 'text'): 'Text · AI review'}


def row(event: OptOutEvent, rules: RuleSet | None) -> dict:
    latest = ContactEvent.objects.filter(client_id=event.client_id, phone_token=event.phone_token).order_by('-occurred_at').first()
    zone = pick_time_zone(None, (latest.time_zones or [None])[0] if latest and latest.time_zones else None,
                          ['recipient_zip', 'area_code', 'America/New_York'])
    deadline = days_left = None
    provisional = True
    if rules:
        found = optout_deadline(event.at, time_zone=zone, rules=rules)
        deadline, provisional = found.date, found.provisional
        today = timezone.now().astimezone(ZoneInfo(zone)).date()
        days_left = BusinessCalendar(rules, today).between(today, deadline) if deadline >= today else 0
    after = ContactEvent.objects.filter(client_id=event.client_id, phone_token=event.phone_token, is_primary=True,
                                        direction='outbound', occurred_at__gt=event.at).order_by('-occurred_at')
    count = after.count()
    end_of_deadline = datetime.combine(deadline, time.max, tzinfo=ZoneInfo(zone)) if deadline else None
    return {
        'id': f'oo-{event.pk}', 'phoneDisplay': latest.masked_label if latest else 'Number hidden',
        'phoneE164': number_ref(event.phone_token) if latest else None,
        'how': HOW.get((event.method, event.channel), event.get_method_display()), 'words': event.keyword or None, 'at': event.at,
        'deadline': deadline, 'businessDaysLeft': days_left or 0, 'deadlineProvisional': provisional,
        'dialerMarked': None,  # checked in Module 9
        'contactsAfter': {'count': count, 'channel': after.first().get_channel_display(), 'lastAt': after.first().occurred_at,
                          'afterDeadline': bool(end_of_deadline and after.filter(occurred_at__gt=end_of_deadline).exists())} if count else None,
    }


class OptOutsView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        try:
            rules = RuleSet()
        except NoRulebook:
            rules = None
        # One row per number: its latest opt-out.
        seen, events = set(), []
        for event in OptOutEvent.objects.filter(client=request.user.client).order_by('-at'):
            if event.phone_token not in seen:
                seen.add(event.phone_token)
                events.append(event)
            if len(events) >= LIMIT:
                break
        return Response([row(e, rules) for e in events])
