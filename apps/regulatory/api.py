"""Client API: the Regulatory Changes page. Everyone reads; the company's lawyer reviews draft rule updates and
suggests changes. Reviews are advice: CiV alone approves a rule update."""
from rest_framework import serializers, status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.recorder import record
from apps.accounts.models import ClientUser
from apps.accounts.permissions import IsClientUser

from .models import ClientSuggestion, RegChange, RegChangeRead, RuleUpdate, RuleUpdateReview
from apps.refs import number

STATUS = {'in_force': 'in force', 'court_ruling': 'court ruling', 'adopted': 'adopted', 'proposed': 'proposed'}
STATE = {'waiting': 'draft', 'approved': 'approved'}


class IsClientLawyer(BasePermission):
    message = "Only your company's lawyer can do this."

    def has_permission(self, request, view):
        return isinstance(request.user, ClientUser) and request.user.is_counsel


def log(request, action: str, obj: str) -> None:
    u = request.user
    record(action, request=request, actor_kind='client_user', actor_id=u.pk, actor_label=u.email, client_id=u.client_id, object=obj[:254])


def pk_of(row_id: str, prefix: str) -> int | None:
    rest = row_id.removeprefix(prefix)
    return number(rest) if row_id.startswith(prefix) else None


def change_row(change: RegChange, read: set[int], reviews: dict[int, RuleUpdateReview]) -> dict:
    updates = []
    for u in change.rule_updates.all():
        if u.state not in STATE:
            continue  # rejected updates are not shown
        mine = reviews.get(u.pk)
        updates.append({'id': f'ru-{u.pk}', 'rule': u.rule_key, 'isNewRule': u.is_new_rule, 'meaning': u.new_meaning or None,
                        'place': 'Federal' if u.jurisdiction == 'US' else u.jurisdiction, 'value': u.shown,
                        'startsOn': u.effective_from, 'state': STATE[u.state],
                        'myReview': {'verdict': mine.verdict, 'comment': mine.comment, 'by': mine.reviewer_name,
                                     'at': mine.reviewed_at} if mine else None})
    return {'id': f'rc-{change.pk}', 'title': change.title, 'jurisdiction': change.jurisdiction, 'status': STATUS[change.status],
            'date': change.announced_on, 'effective': change.effective_text, 'summary': change.summary,
            'settings': change.rule_keys, 'metrics': change.metrics, 'domains': change.domains, 'confirmed': change.pk in read,
            'source': change.source, 'sourceUrl': change.source_url or None,
            'checkedByCounsel': change.review == RegChange.Review.CHECKED, 'updates': updates}


class RegChangesView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        client = request.user.client_id
        read = set(RegChangeRead.objects.filter(client_id=client).values_list('reg_change_id', flat=True))
        reviews = {r.rule_update_id: r for r in RuleUpdateReview.objects.filter(client_id=client)}
        changes = RegChange.objects.prefetch_related('rule_updates')
        from apps.refs import month_span
        if span := month_span(request.query_params.get('period')):  # changes announced by the end of that month (2026-10-30)
            changes = changes.filter(announced_on__lt=span[1])
        return Response([change_row(c, read, reviews) for c in changes])


class ConfirmView(APIView):
    """ "I've read this", for the whole company."""
    permission_classes = [IsClientUser]

    def post(self, request, row_id):
        change = RegChange.objects.filter(pk=pk_of(row_id, 'rc-')).first()
        if change is None:
            return Response({'detail': 'Change not found.'}, status=404)
        RegChangeRead.objects.get_or_create(client_id=request.user.client_id, reg_change=change, defaults={'read_by': request.user.name})
        log(request, 'reg_change_read', change.title)
        return Response({'id': row_id, 'confirmed': True})


class ReviewIn(serializers.Serializer):
    verdict = serializers.ChoiceField(choices=RuleUpdateReview.Verdict.choices)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class ReviewView(APIView):
    """The company's lawyer agrees or disagrees with a draft rule update. It can be changed until CiV decides."""
    permission_classes = [IsClientLawyer]

    def post(self, request, row_id):
        update = RuleUpdate.objects.filter(pk=pk_of(row_id, 'ru-')).first()
        if update is None:
            return Response({'detail': 'Rule update not found.'}, status=404)
        if update.state != RuleUpdate.State.WAITING:
            return Response({'detail': 'CiV has already decided on this update.'}, status=400)
        data = ReviewIn(data=request.data)
        data.is_valid(raise_exception=True)
        review, _ = RuleUpdateReview.objects.update_or_create(
            client_id=request.user.client_id, rule_update=update,
            defaults={'reviewer': request.user, 'reviewer_name': request.user.name, **data.validated_data})
        log(request, 'rule_update_reviewed', f'{update.rule_key}: {review.get_verdict_display()}')
        return Response({'id': row_id, 'verdict': review.verdict, 'comment': review.comment})


class SuggestIn(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    jurisdiction = serializers.CharField(max_length=80)
    summary = serializers.CharField(max_length=4000)
    source = serializers.CharField(max_length=200, required=False, allow_blank=True)
    sourceUrl = serializers.URLField(required=False, allow_blank=True)


class SuggestView(APIView):
    """The company's lawyer tells CiV about a law change. Only CiV sees it."""
    permission_classes = [IsClientLawyer]

    def post(self, request):
        data = SuggestIn(data=request.data)
        data.is_valid(raise_exception=True)
        d = data.validated_data
        suggestion = ClientSuggestion.objects.create(
            client_id=request.user.client_id, suggested_by=request.user.name, title=d['title'], jurisdiction=d['jurisdiction'],
            summary=d['summary'], source=d.get('source', ''), source_url=d.get('sourceUrl', ''))
        log(request, 'law_change_suggested', suggestion.title)
        return Response({'id': f'cs-{suggestion.pk}', 'received': True}, status=status.HTTP_201_CREATED)
