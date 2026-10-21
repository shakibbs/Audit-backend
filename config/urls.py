"""Top-level routes: the CiV admin panel and the client API are kept apart."""
from django.contrib import admin
from django.urls import include, path

from django.conf import settings

from apps.sync.views import hook as sync_hook

from config.health import health
from config.root_redirect import root_redirect

urlpatterns = [
    path('', root_redirect),
    path('civ-admin/', admin.site.urls),
    path('api/health', health),
    path('api/', include('apps.accounts.urls')),
    path('api/', include('apps.rulebook.urls')),
    path('api/', include('apps.regulatory.urls')),
    path('api/', include('apps.sync.urls')),
    path('api/', include('apps.contacts.urls')),
    path('api/', include('apps.optouts.urls')),
    path('api/', include('apps.consent.urls')),
    path('api/', include('apps.captures.urls')),
    path('api/', include('apps.provenance.urls')),
    path('api/', include('apps.access_log.urls')),
    path('api/', include('apps.litigation.urls')),
    path('api/', include('apps.scoring.urls')),
    path('api/', include('apps.findings.urls')),
    path('api/', include('apps.alerts.urls')),
    path('api/', include('apps.reports.urls')),
    path('api/', include('apps.vendors.urls')),
    path('api/', include('apps.evidence.urls')),
    path('api/', include('apps.buyers.urls')),
    path('api/', include('apps.anchoring.urls')),
    path('api/', include('apps.clients.urls')),
    path('api/', include('apps.reconcile.urls')),
    path('api/', include('apps.uploads.urls')),
    path('api/', include('apps.metrics.urls')),
    path('api/', include('apps.onboarding.urls')),
]

# Live notices from clients' tools: off unless SYNC_HOOKS_ENABLED (no public door; CiV asks every 2 minutes instead).
if settings.SYNC_HOOKS_ENABLED:
    urlpatterns.append(path('hooks/<int:connection_id>', sync_hook))
