from django.shortcuts import render
from rest_framework import generics, permissions
from .models import Order
from .serializers import OrderListSerializer
from users.authentication import CustomJWTAuthentication
from django.utils import timezone
from datetime import timedelta
from datetime import datetime

class OrderListView(generics.ListAPIView):
    """
    List all orders with filtering and search capabilities
    GET /api/orders/
    """
    serializer_class = OrderListSerializer
    permission_classes = [permissions.IsAdminUser]
    authentication_classes = [CustomJWTAuthentication]
    ordering = ['-created']
    
    def get_queryset(self):
        # Get the days parameter from query params, default to 15 if not provided or invalid.

        start_date = timezone.now() - timedelta(days=10)
        end_date = timezone.now()
    
        return Order.objects.filter(created__range=(start_date, end_date)).select_related(
            'checkout_session',
            'checkout_session__cart',
            'checkout_session__shipping_address',
            'checkout_session__billing_address',
            'checkout_session__shipping_option'
        ).prefetch_related(
            'status_history',
            'checkout_session__cart__items',
            'checkout_session__cart__items__product'
        )

class OrderDetailView(generics.RetrieveAPIView):
    """
    Retrieve a specific order
    GET /api/orders/<order_id>/
    """
    queryset = Order.objects.all()
    serializer_class = OrderListSerializer
    permission_classes = [permissions.IsAdminUser]
    authentication_classes = [CustomJWTAuthentication]
    lookup_field = 'order_id'

    def get_queryset(self):
        return Order.objects.select_related(
            'checkout_session',
            'checkout_session__cart',
            'checkout_session__shipping_address',
            'checkout_session__billing_address',
            'checkout_session__shipping_option'
        ).prefetch_related(
            'status_history',
            'checkout_session__cart__items',
            'checkout_session__cart__items__product'
        )
