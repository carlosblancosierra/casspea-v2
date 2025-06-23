# views.py

from datetime import datetime, timedelta
import csv

from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Sum, F, ExpressionWrapper, DecimalField
from django.db.models.functions import TruncMonth

from rest_framework import generics, permissions
from rest_framework.decorators import api_view, authentication_classes, permission_classes

from users.authentication import CustomJWTAuthentication
from .models import Order
from .serializers import OrderListSerializer


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
        now = timezone.now()
        start = now - timedelta(days=10)
        end = now

        sd = self.request.query_params.get('start_date')
        ed = self.request.query_params.get('end_date')
        if sd:
            start = timezone.make_aware(datetime.strptime(sd, '%Y-%m-%d'))
            if ed:
                end = timezone.make_aware(datetime.strptime(ed, '%Y-%m-%d')) + timedelta(days=1)

        return (
            Order.objects
            .filter(created__range=(start, end))
            .select_related(
                'checkout_session',
                'checkout_session__cart',
                'checkout_session__shipping_address',
                'checkout_session__billing_address',
                'checkout_session__shipping_option'
            )
            .prefetch_related(
                'status_history',
                'checkout_session__cart__items',
                'checkout_session__cart__items__product',
                'checkout_session__cart__items__box_customization',
                'checkout_session__cart__items__box_customization__allergens',
                'checkout_session__cart__items__pack_customization',
                'checkout_session__cart__items__pack_customization__allergens'
            )
            .order_by('-created')
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
        return (
            Order.objects
            .select_related(
                'checkout_session',
                'checkout_session__cart',
                'checkout_session__shipping_address',
                'checkout_session__billing_address',
                'checkout_session__shipping_option'
            )
            .prefetch_related(
                'status_history',
                'checkout_session__cart__items',
                'checkout_session__cart__items__product',
                'checkout_session__cart__items__box_customization',
                'checkout_session__cart__items__box_customization__flavor_selections',
                'checkout_session__cart__items__box_customization__allergens',
                'checkout_session__cart__items__pack_customization',
                'checkout_session__cart__items__pack_customization__flavor_selections',
                'checkout_session__cart__items__pack_customization__allergens',
                'checkout_session__cart__discount'
            )
        )


@api_view(['GET'])
# @authentication_classes([CustomJWTAuthentication])
# @permission_classes([permissions.IsAdminUser])
def export_product_sales_csv(request):
    """
    CSV download: ventas pagadas por mes y producto.
    Opcionales: ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
    """
    now = timezone.now()
    start = now - timedelta(days=30)
    end = now

    sd = request.query_params.get('start_date')
    ed = request.query_params.get('end_date')
    if sd:
        start = timezone.make_aware(datetime.strptime(sd, '%Y-%m-%d'))
    if ed:
        end = timezone.make_aware(datetime.strptime(ed, '%Y-%m-%d')) + timedelta(days=1)

    qs = (
        Order.objects
        .filter(
            checkout_session__payment_status='paid',
            created__gte=start,
            created__lt=end
        )
        .annotate(month=TruncMonth('created'))
        .values(
            'month',
            product_id=F('checkout_session__cart__items__product__id'),
            product_name=F('checkout_session__cart__items__product__name'),
            product_slug=F('checkout_session__cart__items__product__slug'),
        )
        .annotate(
            total_quantity=Sum('checkout_session__cart__items__quantity'),
            total_cost=Sum(
                ExpressionWrapper(
                    F('checkout_session__cart__items__quantity') *
                    F('checkout_session__cart__items__product__base_price'),
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                )
            )
        )
        .order_by('month', 'product_id')
    )

    resp = HttpResponse(content_type='text/csv')
    resp['Content-Disposition'] = 'attachment; filename="product_sales.csv"'
    writer = csv.writer(resp)
    writer.writerow([
        "Month", "Product ID", "Product Name", "Product Slug",
        "Quantity", "Total Cost"
    ])
    for r in qs:
        writer.writerow([
            r['month'].strftime('%Y-%m'),
            r['product_id'],
            r['product_name'],
            r['product_slug'],
            r['total_quantity'] or 0,
            r['total_cost'] or 0,
        ])

    return resp
