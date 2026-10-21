from django.urls import path

from .api import ConductView, MetricsView, WhoContactView

urlpatterns = [path('metrics', MetricsView.as_view()), path('conduct', ConductView.as_view()),
               path('who-contact', WhoContactView.as_view()), path('who-contact/<str:ref>', WhoContactView.as_view())]
