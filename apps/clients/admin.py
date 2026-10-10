"""Client companies in the admin panel. One page per client: company, connections, users, invites, activity."""
from django.contrib import admin
from django.db.models import Count, Q
from django.urls import path, reverse
from django.utils.formats import date_format
from django.utils.html import format_html

from apps.access_log.labels import action_label
from apps.access_log.models import AccessEntry
from apps.accounts import admin_views as user_views
from apps.accounts.admin import ClientUserInline, InviteInline, save_users
from apps.accounts.models import ClientUser
from apps.admin_panel.base import CivModelAdmin
from apps.billing.admin import ContractInline, save_contract
from apps.billing.models import Contract
from apps.documents import views as document_views
from apps.documents.admin import DocumentInline, save_documents
from apps.documents.models import ClientDocument
from apps.clients import status as stages
from apps.clients.forms import ClientForm
from apps.clients.models import Client, StatusChange
from apps.connections import views as connection_views
from apps.connections.admin import ConnectionInline, key_guide_html, save_connections
from apps.connections.models import Connection, Status
from apps.onboarding import views as onboarding_views
from apps.onboarding.progress import checklist


@admin.register(Client)
class ClientAdmin(CivModelAdmin):
    eyebrow = 'Clients'
    page_sub = 'Click a company to see everything about it: details, connections, users, invites and activity. Search also finds a person by name or email.'
    change_form_outer_before_template = 'clients/client_head.html'
    change_form_after_template = 'clients/client_activity.html'
    form = ClientForm
    list_display = ('name', 'status_shown', 'industry', 'plan', 'onboarding_shown', 'access_shown', 'users_shown', 'connections_shown', 'renews_shown')
    list_display_links = ('name',)
    list_filter = ('status', 'plan', 'counsel_directed', 'access_level')
    search_fields = ('name', 'industry', 'users__email', 'users__name')  # find a person's company by their email
    readonly_fields = ('access_shown', 'status_since', 'created_at')
    inlines = [ConnectionInline, ContractInline, DocumentInline, ClientUserInline, InviteInline]
    fieldsets = (
        (None, {'fields': ('name', 'industry', 'plan', 'start_date', 'status', 'status_reason', 'status_since', 'counsel_directed', 'access_shown', 'created_at')}),
    )

    # A new company has no people yet: show only the Connections tab beside its details.
    def get_inlines(self, request, obj):
        return self.inlines if obj else [ConnectionInline, ContractInline, DocumentInline]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('contract').annotate(
            n_users=Count('users', filter=Q(users__is_active=True), distinct=True),
            n_connections=Count('connections', distinct=True),
            n_connected=Count('connections', filter=Q(connections__status=Status.CONNECTED), distinct=True),
        )

    @admin.display(description='Stage', ordering='status')
    def status_shown(self, client):
        return stages.status_pill(client)

    @admin.display(description='In this stage since')
    def status_since(self, client):
        since = client.status_changed_at or client.created_at
        return date_format(since, 'j M Y · H:i') + ' UTC' if since else '-'

    def save_model(self, request, obj, form, change):
        old = form.initial.get('status', '') if change else ''
        changed = stages.prepare(obj, old)
        super().save_model(request, obj, form, change)
        if changed:
            stages.record_change(request, obj, old, form.cleaned_data.get('status_reason', ''))

    @admin.display(description='Renews', ordering='contract__renewal_date')
    def renews_shown(self, client):
        contract = getattr(client, 'contract', None)
        if not contract or not contract.renewal_date:
            return '-'
        color = 'amber' if contract.renews_soon() else 'gray'
        return format_html('<span class="civ"><span class="pill pill-{}">{}</span></span>', color, date_format(contract.renewal_date, 'j M Y'))

    @admin.display(description='Onboarding')
    def onboarding_shown(self, client):
        progress = checklist(client)
        color = 'green' if progress['complete'] else 'amber'
        return format_html('<span class="civ"><span class="pill pill-{}">{} of {}</span></span>', color, progress['done'], progress['total'])

    @admin.display(description='Data access', ordering='access_level')
    def access_shown(self, client):
        return f'Level {client.access_level} of 4'

    @admin.display(description='Users', ordering='n_users')
    def users_shown(self, client):
        return client.n_users

    @admin.display(description='Connections', ordering='n_connections')
    def connections_shown(self, client):
        return f'{client.n_connected} of {client.n_connections} connected' if client.n_connections else 'None yet'

    def save_formset(self, request, form, formset, change):
        if formset.model is Connection:
            save_connections(request, formset)
        elif formset.model is Contract:
            save_contract(request, formset)
        elif formset.model is ClientDocument:
            save_documents(request, formset)
        elif formset.model is ClientUser:
            save_users(request, formset)
        else:
            super().save_formset(request, form, formset, change)

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        extra = {'key_guide': key_guide_html()}
        if object_id:
            client = Client.objects.filter(pk=object_id).first()
            if client:
                connections = client.connections.all()
                extra.update({
                    'summary': [
                        ('Data access', f'Level {client.access_level}', 'of 4'),
                        ('Connections', connections.filter(status=Status.CONNECTED).count(), f'connected of {connections.count()}'),
                        ('Users', client.users.filter(is_active=True).count(), 'active'),
                        ('Open invites', client.invites.filter(used_at__isnull=True).count(), 'waiting'),
                    ],
                    'onboarding': checklist(client),
                    'status_pill': stages.status_pill(client),
                    'contract': getattr(client, 'contract', None),
                    'status_history': StatusChange.objects.filter(client=client).select_related('changed_by')[:20],
                    'activity': [(e.at, e.actor_label or e.object, *action_label(e.action), e.object if e.actor_label else '')
                                 for e in AccessEntry.objects.filter(client_id=client.pk).order_by('-at')[:10]],
                    'activity_url': reverse('admin:access_log_accessentry_changelist') + f'?client_id__exact={client.pk}',
                })
        return super().changeform_view(request, object_id, form_url, {**extra, **(extra_context or {})})

    def get_urls(self):
        site = self.admin_site
        return [
            path('<int:client_id>/connections/<int:connection_id>/test/', site.admin_view(connection_views.test_connection),
                 name='clients_client_connection_test'),
            path('<int:client_id>/connections/<int:connection_id>/send-link/', site.admin_view(connection_views.send_connect_link),
                 name='clients_client_connection_link'),
            path('<int:client_id>/documents/<int:document_id>/open/', site.admin_view(document_views.open_document),
                 name='clients_client_document_open'),
            path('<int:client_id>/onboarding/<str:step>/', site.admin_view(onboarding_views.toggle_step),
                 name='clients_client_onboarding_toggle'),
            path('<int:client_id>/users/<int:user_id>/password-link/', site.admin_view(user_views.password_link),
                 name='clients_client_user_password_link'),
            *super().get_urls(),
        ]
