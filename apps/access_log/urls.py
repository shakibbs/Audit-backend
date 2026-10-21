from django.urls import path

from .api import AccessLogView

urlpatterns = [path('access-log', AccessLogView.as_view())]
