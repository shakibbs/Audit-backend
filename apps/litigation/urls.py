from django.urls import path

from .api import LitigationView

urlpatterns = [path('litigation', LitigationView.as_view())]
