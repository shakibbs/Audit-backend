from django.urls import path

from .api import UploadsView

urlpatterns = [path('uploads', UploadsView.as_view())]
