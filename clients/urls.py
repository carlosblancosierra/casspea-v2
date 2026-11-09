from django.urls import path

from .views import ClientPageDetailView

urlpatterns = [
    path('<slug:slug>/', ClientPageDetailView.as_view(), name='client-page-detail'),
]
