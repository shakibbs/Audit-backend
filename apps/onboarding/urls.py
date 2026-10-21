from django.urls import path

from .api import ReadinessView

urlpatterns = [path('readiness', ReadinessView.as_view())]
