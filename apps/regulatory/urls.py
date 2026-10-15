from django.urls import path

from .api import ConfirmView, RegChangesView, ReviewView, SuggestView

urlpatterns = [
    path('reg-changes', RegChangesView.as_view()),
    path('reg-changes/suggest', SuggestView.as_view()),
    path('reg-changes/<str:row_id>/confirm', ConfirmView.as_view()),
    path('rule-updates/<str:row_id>/review', ReviewView.as_view()),
]
