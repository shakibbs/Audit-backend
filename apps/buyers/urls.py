from django.urls import path

from .api import LinksView, RevokeView, StatementsView, WithdrawStatementView
from .portal import InsuredsView
from .rating import RatingEngineView, SendView

urlpatterns = [path('buyer-links', LinksView.as_view()), path('buyer-links/<str:ref>/revoke', RevokeView.as_view()),
               path('statements', StatementsView.as_view()), path('statements/<str:ref>/withdraw', WithdrawStatementView.as_view()),
               path('insureds', InsuredsView.as_view()),
               path('rating-engine', RatingEngineView.as_view()), path('rating-engine/send', SendView.as_view())]  # Module 15 step 3: the insurer's portfolio
