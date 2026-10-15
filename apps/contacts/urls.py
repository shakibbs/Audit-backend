from django.urls import path

from .api import CanCallView, ContactsView, NumberView

urlpatterns = [
    path('contacts', ContactsView.as_view()),
    path('evidence/<str:ref>', NumberView.as_view()),
    path('can-call', CanCallView.as_view()),
]
