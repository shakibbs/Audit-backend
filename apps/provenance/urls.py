from django.urls import path

from .api import AnswerView, FileView, LeadsView, ProofRequestsView, ProvenanceView, SearchView, VendorsView

urlpatterns = [
    path('provenance', ProvenanceView.as_view()),
    path('leads', LeadsView.as_view()),
    path('vendors', VendorsView.as_view()),
    path('search', SearchView.as_view()),
    path('proof-requests', ProofRequestsView.as_view()),
    path('proof-requests/<str:ref>/answer', AnswerView.as_view()),
    path('proof-requests/<str:ref>/file', FileView.as_view()),
]
