"""Client companies in the admin panel. One page per client: company, connections, users, invites, activity."""
from django.contrib import admin
from django.db.models import Count, Q
from django.urls import path, reverse
from django.utils.formats import date_format
from django.utils.html import format_html

from apps.access_log.labels import action_label
from apps.access_log.labels import who as who_of
from apps.access_log.models import AccessEntry
from apps.accounts import admin_views as user_views
from apps.accounts.admin import ClientUserInline, InviteInline, NewInviteFormSet, NewInviteInline, invite_by_staff, save_new_invites, save_users
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
from apps.reconcile.summary import completeness_tile
from apps.reconcile.views import completeness_page
from apps.captures.admin import ConsentPageInline, open_photo
from apps.evidence.admin import LegalHoldInline
from apps.provenance.admin import provenance_tile
from apps.conversations.admin import ai_tile


class NeedsAttention(admin.SimpleListFilter):
    """What the Dashboard tiles open (2026-10-23, 2026-10-30): companies with people, waiting invites, working or failed
    connections, or a renewal soon. Each tile counts the same things its list shows."""
    title = 'needs attention'
    parameter_name = 'attention'

    def lookups(self, request, model_admin):
        return [('users', 'With active users'), ('invites', 'Waiting invites'), ('working', 'Working connections'),
                ('connections', 'Failed or stale connections'), ('renewals', 'Renewing within 30 days')]

    def queryset(self, request, queryset):
        from django.utils import timezone

        from apps.billing.models import renewals_within
        if self.value() == 'users':
            return queryset.filter(users__is_active=True).distinct()
        if self.value() == 'working':
            return queryset.filter(connections__status=Status.CONNECTED).distinct()
        if self.value() == 'invites':
            return queryset.filter(invites__used_at__isnull=True, invites__expires_at__gt=timezone.now()).distinct()
        if self.value() == 'connections':
            return queryset.filter(connections__status__in=[Status.FAILED, Status.STALE]).distinct()
        if self.value() == 'renewals':
            return queryset.filter(pk__in=renewals_within(30).values('client_id'))
        return queryset


class Deleted(admin.SimpleListFilter):
    """Deleted companies are hidden from the list but kept with all their records (owner, 2026-10-24)."""
    title = 'deleted'
    parameter_name = 'deleted'

    def lookups(self, request, model_admin):
        return [('yes', 'Deleted companies')]

    def queryset(self, request, queryset):
        return queryset.filter(deleted_at__isnull=False) if self.value() == 'yes' else queryset.filter(deleted_at__isnull=True)


@admin.register(Client)
class ClientAdmin(CivModelAdmin):
    eyebrow = 'Clients'
    page_sub = 'Click a company to see everything about it: details, connections, users, invites and activity. Search also finds a person by name or email.'
    change_form_outer_before_template = 'clients/client_head.html'
    change_form_after_template = 'clients/client_activity.html'
    form = ClientForm
    list_display = ('name', 'status_shown', 'industry', 'plan', 'onboarding_shown', 'access_shown', 'users_shown', 'connections_shown', 'renews_shown')
    list_display_links = ('name',)
    list_filter = (NeedsAttention, 'status', 'plan', 'access_level', Deleted)
    actions = ['restore']
    access_log_deletes = False  # delete_model writes "Company deleted (kept)" itself
    search_fields = ('name', 'industry', 'users__email', 'users__name')  # find a person's company by their email
    readonly_fields = ('access_shown', 'status_since', 'created_at')
    inlines = [ConnectionInline, ContractInline, DocumentInline, ClientUserInline, InviteInline, NewInviteInline, ConsentPageInline, LegalHoldInline]
    fieldsets = (
        (None, {'fields': ('name', 'industry', 'plan', 'start_date', 'status', 'status_reason', 'status_since', 'access_shown', 'created_at')}),
    )

    # A new company has no people yet: show only the Connections tab beside its details.
    def get_inlines(self, request, obj):
        if not obj:
            return [ConnectionInline, ContractInline, DocumentInline]
        # Consent pages and legal holds are read only: shown when viewing, left out of a save (nothing in them is sent back).
        return self.inlines if request.method == 'GET' else [i for i in self.inlines if i not in (ConsentPageInline, LegalHoldInline)]

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

    def get_fieldsets(self, request, obj=None):
        if obj:
            return self.fieldsets
        return (*self.fieldsets, ("Client's Admin", {'fields': ('admin_name', 'admin_email')}))

    # --- Delete = hide and switch off, keep everything; Restore brings it back (owner, 2026-10-24) -------------------
    def delete_model(self, request, obj):
        from django.utils import timezone

        from apps.access_log.recorder import record
        obj.deleted_at, obj.deleted_by, obj.is_active = timezone.now(), request.user.email, False
        obj.save(update_fields=['deleted_at', 'deleted_by', 'is_active'])
        record('client_deleted', request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
               client_id=obj.pk, object=f'{obj.name} · hidden and switched off; all records kept')

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            self.delete_model(request, obj)

    def response_delete(self, request, obj_display, obj_id):
        from django.http import HttpResponseRedirect
        self.message_user(request, f'{obj_display} is deleted: hidden and switched off, with every record kept. '
                                   'Find it under "Deleted companies" to look at it or restore it.')
        return HttpResponseRedirect(reverse('admin:clients_client_changelist'))

    def get_deleted_objects(self, objs, request):
        """The confirm page says what really happens: nothing is erased."""
        lines = [f'{o.name}: hidden from the list and switched off (no sign-in, no reading its tools, insurers lose access). '
                 'Every record and file is kept; open it again with the "Deleted companies" filter and Restore it any time.'
                 for o in objs]
        return lines, {}, set(), []

    @admin.action(description='Restore the selected deleted companies')
    def restore(self, request, queryset):
        from apps.access_log.recorder import record
        restored = 0
        for obj in queryset.filter(deleted_at__isnull=False):
            obj.deleted_at, obj.deleted_by = None, ''
            stages.prepare(obj, obj.status)  # is_active follows the stage again
            obj.save(update_fields=['deleted_at', 'deleted_by', 'is_active'])
            record('client_restored', request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
                   client_id=obj.pk, object=obj.name)
            restored += 1
        self.message_user(request, f'{restored} compan{"y" if restored == 1 else "ies"} restored.')

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.deleted_at:
            return False  # a deleted company is shown read-only; Restore it to change it
        return super().has_change_permission(request, obj)

    def get_inline_instances(self, request, obj=None):
        found = super().get_inline_instances(request, obj)
        if obj is not None and obj.deleted_at:
            for inline in found:  # every tab read-only too
                inline.has_add_permission = lambda *a, **k: False
                inline.has_change_permission = lambda *a, **k: False
                inline.has_delete_permission = lambda *a, **k: False
        return found

    def save_model(self, request, obj, form, change):
        old = form.initial.get('status', '') if change else ''
        changed = stages.prepare(obj, old)
        super().save_model(request, obj, form, change)
        if changed:
            stages.record_change(request, obj, old, form.cleaned_data.get('status_reason', ''))
        if not change:  # the new client's first Admin gets an invitation link
            invite_by_staff(request, obj, email=form.cleaned_data['admin_email'], name=form.cleaned_data['admin_name'], role='admin')

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
        elif isinstance(formset, NewInviteFormSet):
            save_new_invites(request, form.instance, formset)
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
                        certificates_tile(client),
                        completeness_tile(client, reverse('admin:clients_client_completeness', args=[client.pk])),
                        provenance_tile(client),
                        ai_tile(client),
                    ],
                    'onboarding': checklist(client),
                    'status_pill': stages.status_pill(client),
                    'contract': getattr(client, 'contract', None),
                    'status_history': StatusChange.objects.filter(client=client).select_related('changed_by')[:20],
                    'activity': [(e.at, who_of(e), *action_label(e.action), e.object)
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
            path('<int:client_id>/consent-pages/<int:capture_id>/photo/', site.admin_view(open_photo), name='clients_client_page_photo'),
            path('<int:client_id>/completeness/', site.admin_view(completeness_page), name='clients_client_completeness'),
            path('<int:client_id>/users/<int:user_id>/password-link/', site.admin_view(user_views.password_link),
                 name='clients_client_user_password_link'),
            path('<int:client_id>/invites/<int:invite_id>/resend/', site.admin_view(user_views.resend_invite),
                 name='clients_client_invite_resend'),
            *super().get_urls(),
        ]


def certificates_tile(client) -> tuple:
    """Consent certificates claimed for this client, and any waiting, without a key, or lost (Module 3)."""
    from django.db.models import Count

    from apps.certificates.models import CertificateClaim
    counts = dict(CertificateClaim.objects.filter(client=client).values_list('state').annotate(n=Count('id')))
    foot = f"{counts.get('waiting', 0)} waiting · {counts.get('no_key', 0)} no key · {counts.get('lost', 0)} lost"
    return ('Certificates', counts.get('claimed', 0), f'claimed · {foot}')
