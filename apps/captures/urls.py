from django.urls import path

from .api import ConsentPagesView, PagePhotoView

urlpatterns = [
    path('consent-pages', ConsentPagesView.as_view()),
    path('consent-pages/<str:ref>/photo/<str:viewport>', PagePhotoView.as_view()),
]
