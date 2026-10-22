from django.urls import path

from .api import ReadinessView, SetupMarkView

urlpatterns = [path('readiness', ReadinessView.as_view()), path('setup/<str:item>', SetupMarkView.as_view())]
