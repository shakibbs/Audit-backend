from django.urls import path

from .api import OwnInsuredView

urlpatterns = [path('insureds/<str:ref>', OwnInsuredView.as_view())]
