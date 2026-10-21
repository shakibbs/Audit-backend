from django.urls import path

from .api import DomainsView, ScoreView

urlpatterns = [path('score', ScoreView.as_view()), path('domains', DomainsView.as_view())]
