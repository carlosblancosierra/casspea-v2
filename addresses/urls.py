from rest_framework.routers import DefaultRouter
from .views import AddressViewSet, PostalCodeStatsView, SmsContactsView
from django.urls import path, include

router = DefaultRouter()
router.register(r'', AddressViewSet, basename='address')

urlpatterns = [
    path('stats/', PostalCodeStatsView.as_view(), name='postal-code-stats'),
    path('sms-contacts/', SmsContactsView.as_view(), name='sms-contacts'),
    path('', include(router.urls)),
]
