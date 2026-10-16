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
]

# Live notices from clients' tools: off unless SYNC_HOOKS_ENABLED (no public door; CiV asks every 2 minutes instead).
if settings.SYNC_HOOKS_ENABLED:
    urlpatterns.append(path('hooks/<int:connection_id>', sync_hook))
