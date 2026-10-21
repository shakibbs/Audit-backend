from django.urls import path

from .api import HashCheckView, PositionView, VaultView

urlpatterns = [path('vault', VaultView.as_view()), path('position', PositionView.as_view()), path('hash-check', HashCheckView.as_view())]
