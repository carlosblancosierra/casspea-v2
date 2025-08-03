# views.py

from datetime import datetime, timedelta, date
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
from .models import Order, UnitsSold
from .serializers import OrderListSerializer, CustomerOrderSerializer, CustomerShippingDateUpdateSerializer
from flavours.models import Flavour
from flavours.serializers import FlavourSerializer
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from rest_framework import status


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


class CustomerOrderRetrieveView(APIView):
    """
    POST /api/orders/customer/lookup/
    Body: {"order_id": ..., "email": ...}
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        order_id = request.data.get('order_id')
        email = request.data.get('email')
        if not order_id or not email:
            return Response({'detail': 'order_id and email are required.'}, status=400)
        order = get_object_or_404(Order, order_id=order_id)
        if (order.checkout_session.email or '').strip().lower() != email.strip().lower():
            return Response({'detail': 'Order not found.'}, status=404)
        serializer = CustomerOrderSerializer(order)
        return Response(serializer.data)


class CustomerOrderShippingDateUpdateView(APIView):
    """
    POST /api/orders/customer/update-shipping-date/
    Body: {"order_id": ..., "email": ..., "shipping_date": ...}
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        order_id = request.data.get('order_id')
        email = request.data.get('email')
        shipping_date = request.data.get('shipping_date')
        if not order_id or not email or not shipping_date:
            return Response({'detail': 'order_id, email, and shipping_date are required.'}, status=400)
        order = get_object_or_404(Order, order_id=order_id)
        if (order.checkout_session.email or '').strip().lower() != email.strip().lower():
            return Response({'detail': 'Order not found.'}, status=404)
        # Only allow update if not shipped
        if order.status == 'shipped' or order.shipped:
            return Response({'detail': 'Cannot update shipping date after order is shipped.'}, status=400)
        serializer = CustomerShippingDateUpdateSerializer(data={'shipping_date': shipping_date})
        if serializer.is_valid():
            order.checkout_session.cart.shipping_date = serializer.validated_data['shipping_date']
            order.checkout_session.cart.save()
            return Response({'detail': 'Shipping date updated successfully.'})
        return Response(serializer.errors, status=400)


class MonthlyChocolateCountView(APIView):
    """
    GET /api/orders/chocolates-sold/
    Returns: [{"month": "YYYY-MM", "chocolates_sold": N}, ...]
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        paid_orders = Order.objects.filter(checkout_session__payment_status='paid')
        cart_id_to_month = {}
        for order in paid_orders:
            cart_id = order.checkout_session.cart_id
            month = order.created.strftime('%Y-%m')
            cart_id_to_month[cart_id] = month

        from carts.models import CartItem
        cart_items = CartItem.objects.filter(cart_id__in=cart_id_to_month.keys())
        from collections import defaultdict
        monthly_chocolate_counter = defaultdict(int)

        for item in cart_items:
            month = cart_id_to_month.get(item.cart_id)
            if not month:
                continue
            # For each item, count total chocolates (units_per_box * quantity)
            units = item.product.units_per_box * item.quantity
            monthly_chocolate_counter[month] += units

        # Format as list of dicts sorted by month
        data = [
            {"month": month, "chocolates_sold": count}
            for month, count in sorted(monthly_chocolate_counter.items())
        ]
        return Response(data)


class TotalUnitsSoldView(APIView):
    """
    GET /api/orders/total-units-sold/
    Returns: {"total_units_sold": N}
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        paid_orders = Order.objects.filter(checkout_session__payment_status='paid')
        cart_ids = [order.checkout_session.cart_id for order in paid_orders]
        from carts.models import CartItem
        cart_items = CartItem.objects.filter(cart_id__in=cart_ids)
        total_units = sum(item.product.units_per_box * item.quantity for item in cart_items)
        return Response({"total_units_sold": total_units})


class DailyUnitsSoldView(APIView):
    """
    GET /api/orders/daily-units-sold/
    Returns: [{"date": "YYYY-MM-DD", "units_sold": N}, ...]
    For each day, sums units_sold from all sources, but only checks orders and creates UnitsSold for 'ecommerce-v2'.
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        source = 'ecommerce-v2'
        # Find all days with paid orders (ecommerce-v2)
        paid_orders = Order.objects.filter(checkout_session__payment_status='paid')
        from collections import defaultdict
        date_to_cart_ids = defaultdict(list)
        for order in paid_orders:
            order_date = order.created.date()
            cart_id = order.checkout_session.cart_id
            date_to_cart_ids[order_date].append(cart_id)

        from carts.models import CartItem
        today = date.today()
        # For each day with paid orders, ensure UnitsSold for ecommerce-v2 exists
        for day, cart_ids in sorted(date_to_cart_ids.items()):
            if day == today:
                continue  # Do not cache today
            obj, created = UnitsSold.objects.get_or_create(source=source, date=day)
            if created:
                cart_items = CartItem.objects.filter(cart_id__in=cart_ids)
                total_units = sum(item.product.units_per_box * item.quantity for item in cart_items)
                obj.units_sold = total_units
                obj.save()

        # Now, for all days present in UnitsSold, sum all sources for each day
        all_units = UnitsSold.objects.all()
        day_to_total = defaultdict(int)
        for obj in all_units:
            day_to_total[obj.date] += obj.units_sold
        # For today, always calculate on the fly from orders (ecommerce-v2 only)
        if today in date_to_cart_ids:
            cart_items = CartItem.objects.filter(cart_id__in=date_to_cart_ids[today])
            total_units = sum(item.product.units_per_box * item.quantity for item in cart_items)
            day_to_total[today] += total_units
        # Format results
        results = [
            {"date": str(day), "units_sold": units}
            for day, units in sorted(day_to_total.items())
        ]
        total_units = sum(units for units in day_to_total.values())
        return Response({"days": results, "total_units_sold": total_units})
