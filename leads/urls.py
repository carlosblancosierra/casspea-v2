from django.urls import path
from .views import SubscribeNewsletterView, ListLeadsView, CSVLeadsView

app_name = 'mails'

urlpatterns = [
    path('subscribe/', SubscribeNewsletterView.as_view(), name='subscribe'),
    path('list/', ListLeadsView.as_view(), name='list'),
    path('csv/', CSVLeadsView.as_view(), name='csv'),
]
