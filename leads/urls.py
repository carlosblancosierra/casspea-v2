from django.urls import path
from .views import SubscribeNewsletterView, ListLeadsView, CSVLeadsView, GenericLeadSubscribeView, UnsubscribeView

app_name = 'leads'

urlpatterns = [
    path('subscribe/', SubscribeNewsletterView.as_view(), name='subscribe'),
    path('generic-lead/', GenericLeadSubscribeView.as_view(), name='generic-lead-subscribe'),
    path('unsubscribe/', UnsubscribeView.as_view(), name='unsubscribe'),
    path('list/', ListLeadsView.as_view(), name='list'),
    path('csv/', CSVLeadsView.as_view(), name='csv'),
]
