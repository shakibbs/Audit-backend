"""Top-level routes: the CiV admin panel and the client API are kept apart."""
from django.contrib import admin
from django.urls import include, path

from config.health import health
from config.root_redirect import root_redirect

urlpatterns = [
    path('', root_redirect),
    path('civ-admin/', admin.site.urls),
    path('api/health', health),
    path('api/', include('apps.accounts.urls')),
]
