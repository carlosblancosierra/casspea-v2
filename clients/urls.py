from django.urls import path

from .views import ClientPageDetailView, ClientPageUnlockView

urlpatterns = [
    path('<slug:slug>/', ClientPageDetailView.as_view(), name='client-page-detail'),
    path('<slug:slug>/unlock/', ClientPageUnlockView.as_view(), name='client-page-unlock'),
]
