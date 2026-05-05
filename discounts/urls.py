from django.urls import path
from .views import DiscountStatsView

urlpatterns = [
    path('stats/', DiscountStatsView.as_view(), name='discount-stats'),
]
