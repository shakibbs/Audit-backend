from django.urls import path

from .api import AlertsView, ReviewView

urlpatterns = [path('alerts', AlertsView.as_view()), path('alerts/<str:ref>/review', ReviewView.as_view())]
