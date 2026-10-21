"""Client API: the company's own access log (Users & Access → Access log): who signed in, opened a file, answered a
proof request… Newest first. CiV staff actions on the company show as "CiV team"."""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import ClientUser
from apps.accounts.permissions import IsClientUser

from .labels import action_label
from .models import AccessEntry

LIMIT = 300


class AccessLogView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        client = request.user.client
        entries = list(AccessEntry.objects.filter(client_id=client.pk).order_by('-at')[:LIMIT])
        people = {u.pk: u for u in ClientUser.objects.filter(client=client, pk__in={e.actor_id for e in entries if e.actor_id})}
        rows = []
        for e in entries:
            person = people.get(e.actor_id) if e.actor_kind == AccessEntry.ActorKind.CLIENT_USER else None
            actor = person.name if person else 'CiV team' if e.actor_kind == AccessEntry.ActorKind.STAFF else 'CiV' if e.actor_kind == AccessEntry.ActorKind.SYSTEM else e.actor_label or 'Not signed in'
            rows.append({'at': e.at, 'actor': actor, 'role': person.role if person else 'civ', 'action': action_label(e.action)[0], 'object': e.object})
        return Response(rows)
