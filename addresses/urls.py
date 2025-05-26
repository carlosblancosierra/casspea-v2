from rest_framework.routers import DefaultRouter
from .views import AddressViewSet, PostalCodeStatsView
from django.urls import path, include

router = DefaultRouter()
router.register(r'', AddressViewSet, basename='address')

urlpatterns = [
    path('stats/', PostalCodeStatsView.as_view(), name='postal-code-stats'),
    path('', include(router.urls)),
]
