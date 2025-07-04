# views.py

from datetime import datetime, timedelta
import csv
from django.contrib.postgres.aggregates import ArrayAgg
from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Sum, F, ExpressionWrapper, DecimalField
from django.db.models.functions import TruncMonth

from rest_framework import generics, permissions
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import SessionAuthentication

from users.authentication import CustomJWTAuthentication
from .models import Order
from .serializers import OrderListSerializer
from flavours.models import Flavour
from flavours.serializers import FlavourSerializer
from rest_framework.response import Response
from rest_framework.views import APIView


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
        qs = Order.objects.select_related(
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
        )

        # 1) Rango de fechas como antes…
        now = timezone.now()
        start = now - timedelta(days=10)
        end = now
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if start_date:
            start = timezone.make_aware(
                datetime.strptime(start_date, '%Y-%m-%d')
            )
            if end_date:
                end = timezone.make_aware(
                    datetime.strptime(end_date, '%Y-%m-%d')
                ) + timedelta(days=1)
        qs = qs.filter(created__range=(start, end))

        # 2) Pre-cargar el mapa email → [order_id de pagados]
        emails = qs.values_list('checkout_session__email', flat=True).distinct()
        paid = (
            Order.objects
            .filter(
                checkout_session__email__in=emails,
                checkout_session__payment_status='paid'
            )
            .values('checkout_session__email')
            .annotate(past_orders=ArrayAgg('order_id'))
        )
        self.past_ids_map = {
            item['checkout_session__email'] or '': item['past_orders']
            for item in paid
        }
        return qs.order_by('-created')


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
@authentication_classes([CustomJWTAuthentication, SessionAuthentication])
@permission_classes([permissions.IsAdminUser])
def export_product_sales_csv(request):
    """
    CSV download: ventas pagadas por mes y producto.
    Opcionales: ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
    """
    sd = request.query_params.get('start_date')
    ed = request.query_params.get('end_date')
    if sd:
        start = timezone.make_aware(datetime.strptime(sd, '%Y-%m-%d'))
    else:
        start = timezone.make_aware(datetime(2025, 1, 1))
    if ed:
        end = timezone.make_aware(datetime.strptime(ed, '%Y-%m-%d')) + timedelta(days=1)
    else:
        end = timezone.make_aware(datetime(2026, 1, 1))

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


def get_monthly_flavour_data():
    paid_orders = Order.objects.filter(
        checkout_session__payment_status='paid'
    )
    cart_id_to_month = {}
    for order in paid_orders:
        cart_id = order.checkout_session.cart_id
        month = order.created.strftime('%Y-%m')
        cart_id_to_month[cart_id] = month

    from carts.models import CartItem
    cart_items = CartItem.objects.filter(cart_id__in=cart_id_to_month.keys())
    from collections import defaultdict
    monthly_flavour_counter = defaultdict(lambda: defaultdict(int))

    for item in cart_items:
        month = cart_id_to_month.get(item.cart_id)
        if not month:
            continue
        # Box customization
        if hasattr(item, 'box_customization') and item.box_customization:
            if (
                item.box_customization.selection_type == 'RANDOM'
                and item.box_customization.flavor_selections.count() == 0
            ):
                monthly_flavour_counter['random'][month] += (
                    item.product.units_per_box * item.quantity
                )
            else:
                for fs in item.box_customization.flavor_selections.all():
                    monthly_flavour_counter[fs.flavor_id][month] += (
                        fs.quantity * item.quantity
                    )
        # Pack customization
        if hasattr(item, 'pack_customization') and item.pack_customization:
            if (
                item.pack_customization.selection_type == 'RANDOM'
                and item.pack_customization.flavor_selections_pack.count() == 0
            ):
                monthly_flavour_counter['random'][month] += (
                    item.product.units_per_box * item.quantity
                )
            else:
                for fs in item.pack_customization.flavor_selections_pack.all():
                    monthly_flavour_counter[fs.flavor_id][month] += (
                        fs.quantity * item.quantity
                    )
    # Prepare data for both views
    flavour_ids = [fid for fid in monthly_flavour_counter.keys() if fid != 'random']
    flavour_names = dict(Flavour.objects.filter(id__in=flavour_ids).values_list('id', 'name'))
    return monthly_flavour_counter, flavour_names


class FlavoursSoldView(APIView):
    permission_classes = [permissions.IsAdminUser]
    authentication_classes = [CustomJWTAuthentication, SessionAuthentication]

    def get(self, request):
        monthly_flavour_counter, flavour_names = get_monthly_flavour_data()
        data = []
        flavour_ids = [fid for fid in monthly_flavour_counter.keys() if fid != 'random']
        for flavour_id in flavour_ids:
            data.append({
                'name': flavour_names.get(flavour_id, str(flavour_id)),
                'monthly': dict(monthly_flavour_counter[flavour_id])
            })
        if 'random' in monthly_flavour_counter:
            data.append({
                'name': 'Random',
                'monthly': dict(monthly_flavour_counter['random'])
            })
        return Response(data)


class FlavoursSoldCSVView(APIView):
    permission_classes = [permissions.IsAdminUser]
    authentication_classes = [CustomJWTAuthentication, SessionAuthentication]

    def get(self, request):
        monthly_flavour_counter, flavour_names = get_monthly_flavour_data()
        import csv
        from django.http import HttpResponse
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="flavours_sold_monthly.csv"'
        writer = csv.writer(response)
        writer.writerow(['Flavour', 'Month', 'Quantity'])
        flavour_ids = [fid for fid in monthly_flavour_counter.keys() if fid != 'random']
        for flavour_id in flavour_ids:
            name = flavour_names.get(flavour_id, str(flavour_id))
            for month, qty in monthly_flavour_counter[flavour_id].items():
                writer.writerow([name, month, qty])
        if 'random' in monthly_flavour_counter:
            for month, qty in monthly_flavour_counter['random'].items():
                writer.writerow(['Random', month, qty])
        return response
