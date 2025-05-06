from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CheckoutViewSet
from checkout.stripe_views import StripeCheckoutSessionView, StripeSuccessView, StripeCancelView, StripeCheckoutSessionEmbeddedView, StripeCheckoutResultView
from checkout.webhooks import stripe_webhook

router = DefaultRouter()
router.register(r'session', CheckoutViewSet, basename='session')

urlpatterns = [
    path('', include(router.urls)),
    path('stripe/create-session/', StripeCheckoutSessionView.as_view(), name='stripe-create-session'),
    path('stripe/embedded/create-session/', StripeCheckoutSessionEmbeddedView.as_view(), name='stripe-create-session-embedded'),
    path('stripe/embedded/result/', StripeCheckoutResultView.as_view(), name='stripe-result'),
    path('stripe/success/', StripeSuccessView.as_view(), name='stripe-success'),
    path('stripe/cancel/', StripeCancelView.as_view(), name='stripe-cancel'),
    path('stripe/webhook/', stripe_webhook, name='stripe-webhook'),
]
