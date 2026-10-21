"""Client API: the Action Queue (Module 11). GET /api/actions — the findings, most urgent first. PATCH /api/actions/<id>
(step 2; Admins and the company's lawyer only) — owner, due date, status, the decision with its note, and a dispute.
Every change is written to the access log; for the decision, only the note's fingerprint (spec §9)."""
import hashlib

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.recorder import record
from apps.accounts.models import ClientUser
from apps.accounts.permissions import IsClientUser

from .build import plural, ranked
from .catalog import RESPONSES
from .models import Finding

DECISIONS = {'accepted', 'declined', 'alternative'}
STATUSES = {'open', 'in_progress', 'resolved'}


def row(f: Finding, rank: int, today, gain: float | None = None) -> dict:
    impact = f'+{gain:.1f}' if gain else (plural(f.affected, 'contact') if f.affected else ('Missing data' if f.key.endswith('-worst') else '—'))
    gone = f.status == Finding.Status.RESOLVED
    state = 'resolved' if gone else f.work_status
    return {'id': f'f-{f.pk}', 'rank': rank, 'severity': f.severity, 'title': f.title, 'why': f.why, 'domain': f.domain,
            'owner': 'you', 'impact': impact, 'fixStep': RESPONSES.get(f.key, RESPONSES.get(f.metric, '')), 'fixStepDraft': True,
            'assignee': f.assignee.name if f.assignee else None, 'due': f.due.isoformat() if f.due else None,
            'overdue': bool(f.due and f.due < today and state != 'resolved'), 'status': state,
            'dispute': {'note': f.dispute_note, 'by': f.dispute_by, 'at': f.dispute_at.isoformat()} if f.dispute_note else None,
            'decision': {'choice': f.decision, 'note': f.decision_note, 'by': f.decided_by, 'at': f.decided_at.date().isoformat()} if f.decision else None,
            'metric': f.metric, 'examples': f.examples, 'numbersAffected': f.numbers, 'since': f.first_seen.date().isoformat(),
            'reopened': f.status == Finding.Status.REOPENED, 'resolvedOn': f.resolved_at.date().isoformat() if gone and f.resolved_at else None}


def can_decide(user) -> bool:
    return user.is_admin or user.is_counsel


class ActionsView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        from apps.alerts.api import can_see
        if not can_see(request.user):
            return Response([])  # lawyer-only mode: Admins and the company's lawyer only (as the portal)
        from apps.scoring.portal import impact
        today, client = timezone.localdate(), request.user.client
        rows = ranked(client)
        gains = {m: impact(client, m) for m in {f.metric for f in rows if f.status != 'resolved'}}
        return Response([row(f, i, today, gains.get(f.metric)) for i, f in enumerate(rows, 1)])


class ActionView(APIView):
    permission_classes = [IsClientUser]

    def patch(self, request, ref: str):
        user = request.user
        if not can_decide(user):
            return Response({'detail': 'Only an Admin or your lawyer can change a finding.'}, status=status.HTTP_403_FORBIDDEN)
        pk = ref.removeprefix('f-')
        f = Finding.objects.filter(client=user.client, pk=int(pk) if pk.isdigit() else 0).first()
        if f is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        data, changed = request.data, []
        if 'assignee' in data:
            name = data['assignee'] or None
            person = ClientUser.objects.filter(client=user.client, is_active=True, name=name).first() if name else None
            if name and person is None:
                return Response({'detail': 'Pick one of your active users.'}, status=status.HTTP_400_BAD_REQUEST)
            f.assignee = person
            changed.append(f'assigned to {person.name if person else "nobody"}')
        if 'due' in data:
            try:
                f.due = timezone.datetime.fromisoformat(data['due']).date() if data['due'] else None
            except ValueError:
                return Response({'detail': 'Give the due date as YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
            changed.append(f'due {f.due or "none"}')
        if 'status' in data:
            if data['status'] not in STATUSES:
                return Response({'detail': 'Unknown status.'}, status=status.HTTP_400_BAD_REQUEST)
            f.work_status = data['status']
            changed.append(f'status {f.work_status}')
        if 'decision' in data:
            choice, note = (data['decision'] or {}).get('choice'), ((data['decision'] or {}).get('note') or '').strip()
            if choice not in DECISIONS:
                return Response({'detail': 'Choose Accepted, Declined or Other plan.'}, status=status.HTTP_400_BAD_REQUEST)
            f.decision, f.decision_note, f.decided_by, f.decided_at = choice, note, user.name, timezone.now()
            f.note_sha256 = hashlib.sha256(note.encode()).hexdigest() if note else ''
            changed.append(f'decided {choice}' + (f' · note sha256 {f.note_sha256[:16]}' if note else ''))
        if 'dispute' in data:
            note = ((data['dispute'] or {}).get('note') or '').strip()
            if not note:
                return Response({'detail': 'Say what the measurement missed.'}, status=status.HTTP_400_BAD_REQUEST)
            f.dispute_note, f.dispute_by, f.dispute_at = note, user.name, timezone.localdate()
            changed.append('disputed')
        if not changed:
            return Response({'detail': 'Nothing to change.'}, status=status.HTTP_400_BAD_REQUEST)
        f.save()
        record('finding_changed', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email,
               client_id=user.client_id, object=f'{f.title} · {"; ".join(changed)}'[:254])
        return Response(row(f, 0, timezone.localdate()))
