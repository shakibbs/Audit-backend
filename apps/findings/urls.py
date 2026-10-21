from django.urls import path

from .api import ActionsView, ActionView

urlpatterns = [path('actions', ActionsView.as_view()), path('actions/<str:ref>', ActionView.as_view())]
