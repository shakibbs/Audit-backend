from django.urls import path

from .api import OptOutsView

urlpatterns = [path('optouts', OptOutsView.as_view())]
