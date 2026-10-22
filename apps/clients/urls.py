from django.urls import path

from .api import BilledNumbersView, NotificationsView, RevocationView, SettingsView

urlpatterns = [
    path('settings', SettingsView.as_view()),
    path('settings/email/notifications', NotificationsView.as_view()),
    path('revocation', RevocationView.as_view()),
    path('billed-numbers', BilledNumbersView.as_view()),
]
