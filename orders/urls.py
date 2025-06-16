from django.urls import path
from . import views
from mails import views as mails_views

app_name = 'orders'

urlpatterns = [
    path('', views.OrderListView.as_view(), name='order-list'),
    path('<str:order_id>/', views.OrderDetailView.as_view(), name='order-detail'),
    path('send-tracking-code-mail/', mails_views.OrderShippingEmailView.as_view(), name='send-tracking-code-mail'),
]
