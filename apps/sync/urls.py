from django.urls import path

from .api import DataHealthView, SourcesView

urlpatterns = [
    path('sources', SourcesView.as_view()),
    path('data-health', DataHealthView.as_view()),
]
