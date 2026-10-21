from django.urls import path

from .api import CalendarView, RulebookView, SnapshotView

urlpatterns = [
    path('rulebook', RulebookView.as_view()),
    path('rulebook/calendar', CalendarView.as_view()),
    path('rulebook/snapshot', SnapshotView.as_view()),
]
