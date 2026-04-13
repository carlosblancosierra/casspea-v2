from django.urls import path
from mails.views import OrderShippingEmailView, ReviewRequestPreviewView, ReviewRequestSendView, EmailOpenTrackingView

urlpatterns = [
    path('shipping-email/', OrderShippingEmailView.as_view(), name='order-shipping-email'),
    path('review-request-preview/', ReviewRequestPreviewView.as_view(), name='review-request-preview'),
    path('review-request-send/', ReviewRequestSendView.as_view(), name='review-request-send'),
    path('track/<uuid:token>/open.gif', EmailOpenTrackingView.as_view(), name='email-open-tracking'),
]
