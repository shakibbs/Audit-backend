from django.urls import path

from .api import CertificatesView, ConsentView

urlpatterns = [
    path('consent', ConsentView.as_view()),
    path('certificates', CertificatesView.as_view()),
]
