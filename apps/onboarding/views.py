"""Tick or untick a manual onboarding step on a client's page."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.access_log.recorder import record
from apps.clients.models import Client
from apps.onboarding.models import OnboardingTick
from apps.onboarding.steps import MANUAL_CODES, STEPS


@require_POST
def toggle_step(request, client_id, step):
    if not request.user.has_perm('clients.change_client') or step not in MANUAL_CODES:
        raise PermissionDenied
    client = get_object_or_404(Client, pk=client_id)
    label = next(s.label for s in STEPS if s.code == step)
    tick = OnboardingTick.objects.filter(client=client, step=step).first()
    if tick:
        tick.delete()
        action, text = 'onboarding_step_undone', f'"{label}" marked as not done.'
    else:
        OnboardingTick.objects.create(client=client, step=step, done_by=request.user)
        action, text = 'onboarding_step_done', f'"{label}" done.'
    record(action, request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
           client_id=client.pk, object=label)
    messages.info(request, text)
    return redirect(reverse('admin:clients_client_change', args=[client.pk]))
