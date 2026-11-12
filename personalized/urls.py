from django.urls import path
from .views import TemplateListView, TemplateDetailView, PersonalisedRequestView

urlpatterns = [
    path('templates/', TemplateListView.as_view(), name='template-list'),
    path('templates/<slug:slug>/', TemplateDetailView.as_view(), name='template-detail'),
    path('send-request/', PersonalisedRequestView.as_view(), name='send-request'),
]
