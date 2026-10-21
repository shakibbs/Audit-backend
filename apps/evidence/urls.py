from django.urls import path

from .api import BundleView, EvidenceFileView, HoldsView, RefetchView, ReleaseHoldView

urlpatterns = [path('evidence-file/<str:ref>', EvidenceFileView.as_view()), path('evidence-file/<str:ref>/refetch', RefetchView.as_view()),
               path('evidence-bundle', BundleView.as_view()),
               path('legal-holds', HoldsView.as_view()), path('legal-holds/<str:ref>/release', ReleaseHoldView.as_view())]
