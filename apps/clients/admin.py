"""Clients section of the admin panel."""
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from apps.admin_panel.base import CivModelAdmin
from apps.clients.models import Client
from apps.connections.admin import ConnectionInline


@admin.register(Client)
class ClientAdmin(CivModelAdmin):
    eyebrow = 'Clients'
    page_sub = 'Every client company, its plan, lawyer-only mode and how much of its data CiV can read.'
    list_display = ('name', 'industry', 'plan', 'access_shown', 'start_date', 'counsel_directed', 'is_active')
    list_filter = ('plan', 'is_active', 'counsel_directed', 'access_level')
    search_fields = ('name', 'industry')
    readonly_fields = ('access_shown', 'add_connection', 'created_at')
    inlines = [ConnectionInline]

    @admin.display(description='Connections')
    def add_connection(self, client):
        if not client.pk:
            return 'Save the company first, then add its tools.'
        url = reverse('admin:connections_connection_add') + f'?client={client.pk}'
        return format_html('<a class="civ-btn" href="{}">+ Add connection</a>', url)

    @admin.display(description='Data access level', ordering='access_level')
    def access_shown(self, client):
        return f'Level {client.access_level} of 4'
