"""Client API (Module 15 step 1): GET /api/buyer-links — who this company shares with; POST /api/buyer-links
{name, email, person, kind, endsOn} — share with its insurer or acquirer by the underwriter's email (Admins; an acquirer
needs an end date; owner decision 2026-10-22: the client invites, CiV staff only see and block);
POST /api/buyer-links/bl-<id>/revoke — stop sharing (the buyer loses access at its next request). Every change is
logged."""
from datetime import date

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.recorder import record
from apps.accounts.permissions import IsClientUser

from .models import BuyerLink, BuyerOrg


def link_row(link: BuyerLink, today) -> dict:
    return {'id': f'bl-{link.pk}', 'org': link.org.name, 'kind': link.org.kind, 'grantedBy': link.granted_by, 'grantedOn': link.granted_at.date(),
            'endsOn': link.ends_on, 'stoppedOn': link.revoked_at.date() if link.revoked_at else None, 'active': link.active(today)}


def log(request, action: str, obj: str) -> None:
    user = request.user
    record(action, request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email, client_id=user.client_id, object=obj[:254])


class LinksView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        today = timezone.localdate()
        links = BuyerLink.objects.filter(client=request.user.client).select_related('org')
        return Response({'links': [link_row(link, today) for link in links]})

    def post(self, request):
        from .invite import share
        user = request.user
        if not user.is_admin:
            return Response({'detail': 'Only an Admin can share your data with an insurer.'}, status=status.HTTP_403_FORBIDDEN)
        kind = request.data.get('kind') or BuyerOrg.Kind.INSURER
        if kind not in BuyerOrg.Kind.values:
            return Response({'detail': 'Choose insurer or acquirer.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            ends = date.fromisoformat(request.data['endsOn']) if request.data.get('endsOn') else None
        except ValueError:
            return Response({'detail': 'Give the end date as YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
        if ends and ends < timezone.localdate():
            return Response({'detail': 'The end date has passed.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            link, invited = share(user.client, user.name, str(request.data.get('name') or ''), str(request.data.get('email') or ''), kind, ends,
                                  str(request.data.get('person') or ''))
        except ValueError as problem:
            return Response({'detail': str(problem)}, status=status.HTTP_400_BAD_REQUEST)
        log(request, 'buyer_link_granted', f'{link.org.name} · {request.data.get("email")}' + (f' until {ends}' if ends else '') + (' · invite sent' if invited else ''))
        return Response({**link_row(link, timezone.localdate()), 'invited': invited}, status=status.HTTP_201_CREATED)


class RevokeView(APIView):
    permission_classes = [IsClientUser]

    def post(self, request, ref: str):
        user = request.user
        if not user.is_admin:
            return Response({'detail': 'Only an Admin can stop sharing.'}, status=status.HTTP_403_FORBIDDEN)
        pk = ref.removeprefix('bl-')
        link = BuyerLink.objects.filter(client=user.client, pk=int(pk) if pk.isdigit() else 0, revoked_at__isnull=True).select_related('org').first()
        if link is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        link.revoked_by, link.revoked_at = user.name, timezone.now()
        link.save(update_fields=['revoked_by', 'revoked_at'])
        log(request, 'buyer_link_revoked', link.org.name)
        return Response(link_row(link, timezone.localdate()))


class StatementsView(APIView):
    """GET /api/statements · POST {topic, text} — the company's signed statements for its insurer (Admins and the
    lawyer sign; owner decision 2026-10-22: written on its own Risk Attestation page). POST
    /api/statements/st-<id>/withdraw takes one back. Statements never raise a value; CiV shows conflicts."""
    permission_classes = [IsClientUser]

    def get(self, request):
        from .attestation import statements
        return Response(statements(request.user.client)['statementRows'])

    def post(self, request):
        from .models import Statement
        user = request.user
        if not (user.is_admin or user.is_counsel):
            return Response({'detail': 'Only an Admin or your lawyer can sign a statement.'}, status=status.HTTP_403_FORBIDDEN)
        text = ' '.join(str(request.data.get('text') or '').split())
        topic = request.data.get('topic') or Statement.Topic.OTHER
        if topic not in Statement.Topic.values:
            return Response({'detail': 'Choose what the statement is about.'}, status=status.HTTP_400_BAD_REQUEST)
        if not text:
            text = Statement.Topic(topic).label if topic != Statement.Topic.OTHER else ''
        if not text:
            return Response({'detail': 'Write the statement.'}, status=status.HTTP_400_BAD_REQUEST)
        s = Statement.objects.create(client=user.client, topic=topic, text=text[:500], signed_by=user.name)
        log(request, 'statement_signed', f'{s.get_topic_display()} · {s.text}')
        return Response({'id': f'st-{s.pk}'}, status=status.HTTP_201_CREATED)


class WithdrawStatementView(APIView):
    permission_classes = [IsClientUser]

    def post(self, request, ref: str):
        from .models import Statement
        user = request.user
        if not (user.is_admin or user.is_counsel):
            return Response({'detail': 'Only an Admin or your lawyer can withdraw a statement.'}, status=status.HTTP_403_FORBIDDEN)
        pk = ref.removeprefix('st-')
        s = Statement.objects.filter(client=user.client, pk=int(pk) if pk.isdigit() else 0, withdrawn_at__isnull=True).first()
        if s is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        s.withdrawn_at = timezone.now()
        s.save(update_fields=['withdrawn_at'])
        log(request, 'statement_withdrawn', s.text)
        return Response({'id': ref, 'withdrawn': True})
