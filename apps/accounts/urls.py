"""Client login API routes, mounted under /api/."""
from django.urls import path

from apps.accounts.views.invites import AcceptInviteView, InviteCheckView
from apps.accounts.views.password_reset import ResetConfirmView, ResetRequestView
from apps.accounts.views.session import SessionView
from apps.accounts.views.sign_in import SignInView
from apps.accounts.views.sign_out import SignOutView
from apps.accounts.views.users import UserDetailView, UsersView

urlpatterns = [
    path('session', SessionView.as_view()),
    path('session/sign-in', SignInView.as_view()),
    path('session/sign-out', SignOutView.as_view()),
    path('session/reset', ResetRequestView.as_view()),
    path('session/reset/confirm', ResetConfirmView.as_view()),
    path('invites/check', InviteCheckView.as_view()),
    path('invites/accept', AcceptInviteView.as_view()),
    path('users', UsersView.as_view()),
    path('users/<str:row_id>', UserDetailView.as_view()),
]
