"""Admin page: one client's records completeness, every tool, how it was checked."""
from django.contrib import admin
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import reverse

from apps.clients.models import Client

from .summary import completeness_months


def completeness_page(request, client_id: int):
    client = get_object_or_404(Client, pk=client_id)
    return TemplateResponse(request, 'reconcile/completeness.html', {
        **admin.site.each_context(request), 'title': f'Records completeness · {client.name}', 'client': client,
        'months': completeness_months(client),
        'back_url': reverse('admin:clients_client_change', args=[client.pk])})
