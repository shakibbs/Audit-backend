from django.urls import path

from .api import CalendarView, RulebookView

urlpatterns = [
    path('rulebook', RulebookView.as_view()),
    path('rulebook/calendar', CalendarView.as_view()),
]
