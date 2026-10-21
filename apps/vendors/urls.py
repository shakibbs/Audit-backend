from django.urls import path

from .api import ContractFileView, ContractsView, DisputesView

urlpatterns = [path('vendor-contracts', ContractsView.as_view()), path('vendor-contracts/<str:ref>/file', ContractFileView.as_view()),
               path('vendor-disputes', DisputesView.as_view())]
