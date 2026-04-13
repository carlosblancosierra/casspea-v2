from django.urls import path
from mails.views import OrderShippingEmailView, ReviewRequestPreviewView

urlpatterns = [
    path('shipping-email/', OrderShippingEmailView.as_view(), name='order-shipping-email'),
    path('review-request-preview/', ReviewRequestPreviewView.as_view(), name='review-request-preview'),
]
