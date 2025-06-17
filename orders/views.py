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

        if self.request.query_params.get('start_date'):
            start_date = datetime.strptime(self.request.query_params.get('start_date'), '%Y-%m-%d')
            start_date = timezone.make_aware(start_date)
            if self.request.query_params.get('end_date'):
                end_date = datetime.strptime(self.request.query_params.get('end_date'), '%Y-%m-%d')
                end_date = timezone.make_aware(end_date) + timedelta(days=1)

        print("start_date", start_date)
        print("end_date", end_date)

        return Order.objects.filter(created__range=(start_date, end_date)).select_related(
            'checkout_session',
            'checkout_session__cart',
            'checkout_session__shipping_address',
            'checkout_session__billing_address',
            'checkout_session__shipping_option'
        ).prefetch_related(
            'status_history',
            'checkout_session__cart__items',
            'checkout_session__cart__items__product',
            'checkout_session__cart__items__box_customization',
            'checkout_session__cart__items__box_customization__flavor_selections',
            'checkout_session__cart__items__box_customization__flavor_selections__flavor',
            'checkout_session__cart__items__box_customization__allergens',
            'checkout_session__cart__items__pack_customization',
            'checkout_session__cart__items__pack_customization__flavor_selections',
            'checkout_session__cart__items__pack_customization__flavor_selections__flavor',
            'checkout_session__cart__items__pack_customization__allergens'
        ).order_by('-created')


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
            'checkout_session__cart__items__product',
            'checkout_session__cart__items__box_customization',
            'checkout_session__cart__items__pack_customization',
            'checkout_session__cart__items__box_customization__flavor_selections',
            'checkout_session__cart__items__pack_customization__flavor_selections',
            'checkout_session__cart__items__box_customization__allergens',
            'checkout_session__cart__items__pack_customization__allergens',
            'checkout_session__cart__discount'
        )
