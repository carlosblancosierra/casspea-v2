from datetime import datetime, timedelta, time
import csv
from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Sum, F, ExpressionWrapper, DecimalField
from django.db.models.functions import TruncMonth

from rest_framework import generics, permissions
from rest_framework.pagination import PageNumberPagination
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import SessionAuthentication

from users.authentication import CustomJWTAuthentication
from .models import Order, UnitsSold
from .serializers import (
    OrderListSerializer,
    OrderSummarySerializer,
    CustomerOrderSerializer,
    CustomerShippingDateUpdateSerializer,
)
from flavours.models import Flavour
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from collections import defaultdict
from django.db.models import IntegerField
from carts.models import CartItem
from django.db.models import Max, OuterRef, Subquery, Q
from rest_framework import status


# Everything OrderListSerializer touches, in one place.
#
# The two views that serve an order had their own copies of this list, and the
# pack line in both named `flavor_selections` — but that related_name belongs
# to the BOX side. The pack side is `flavor_selections_pack`
# (carts/models.py: CartItemBoxFlavorSelection), so `/api/orders/` raised
# AttributeError on every request. prefetch_related does not validate its
# arguments until the queryset is evaluated, so nothing complained at import
# or in a system check — it simply 500'd in production.
ORDER_SELECT_RELATED = (
    'checkout_session',
    'checkout_session__cart',
    'checkout_session__shipping_address',
    'checkout_session__billing_address',
    'checkout_session__shipping_option',
)

# A ceiling on ?ids=, which returns the whole object graph per order. Staff
# pick a day or two's worth to prepare, not a year's.
MAX_ORDER_IDS = 200

ORDER_PREFETCH_RELATED = (
    'status_history',
    'checkout_session__cart__items',
    'checkout_session__cart__items__product',
    'checkout_session__cart__items__box_customization',
    'checkout_session__cart__items__box_customization__flavor_selections',
    'checkout_session__cart__items__box_customization__allergens',
    'checkout_session__cart__items__pack_customization',
    'checkout_session__cart__items__pack_customization__flavor_selections_pack',
    'checkout_session__cart__items__pack_customization__allergens',
    'checkout_session__cart__discount',
)


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
        qs = (
            Order.objects
            .select_related(*ORDER_SELECT_RELATED)
            .prefetch_related(*ORDER_PREFETCH_RELATED)
        )

        # Explicit order ids win over the date range. The production-totals
        # screen lets staff tick orders from any page of the table, so the
        # dates they happen to be browsing must not silently drop a selected
        # order from the totals they are about to bake to.
        ids = self.request.query_params.get('ids')
        if ids:
            wanted = [value.strip() for value in ids.split(',') if value.strip()][:MAX_ORDER_IDS]
            qs = qs.filter(order_id__in=wanted)
        else:
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
        #
        # Grouped in Python rather than with ArrayAgg, which is Postgres-only.
        # It is still one query, and it is the difference between this view
        # being testable everywhere and not being testable at all: the test
        # that covers it used to be skipped outside Postgres, which is how a
        # broken prefetch path reached production (#14).
        emails = qs.values_list('checkout_session__email', flat=True).distinct()
        paid = (
            Order.objects
            .filter(
                checkout_session__email__in=emails,
                checkout_session__payment_status='paid'
            )
            .values_list('checkout_session__email', 'order_id')
        )
        past_ids_map = defaultdict(list)
        for email, order_id in paid:
            past_ids_map[email or ''].append(order_id)
        self.past_ids_map = dict(past_ids_map)
        return qs.order_by('-created')


class OrderSummaryPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class OrderSummaryListView(generics.ListAPIView):
    """
    Light, paginated list for the orders table.
    GET /api/orders/summary/

    Returns one flat row per order instead of the whole object graph, so a page
    of orders is a handful of queries and a small payload. The detail drawer
    fetches the full order from OrderDetailView on demand.

    Kept separate from OrderListView so the existing orders view, which needs
    the nested data, keeps working unchanged.
    """
    serializer_class = OrderSummarySerializer
    permission_classes = [permissions.IsAdminUser]
    authentication_classes = [CustomJWTAuthentication]
    pagination_class = OrderSummaryPagination

    def get_queryset(self):
        qs = Order.objects.select_related(
            'checkout_session',
            'checkout_session__cart',
            'checkout_session__cart__discount',
            'checkout_session__shipping_address',
            'checkout_session__shipping_option',
        ).prefetch_related(
            # Not serialized, but total_with_shipping walks the cart to compute
            # the total, so without these the page costs two queries per order.
            'checkout_session__cart__items',
            'checkout_session__cart__items__product',
            'checkout_session__cart__discount__exclusions',
        )

        # Total units per order, as a subquery so it cannot fan out the rows.
        item_count = (
            CartItem.objects
            .filter(cart=OuterRef('checkout_session__cart'))
            .values('cart')
            .annotate(total=Sum('quantity'))
            .values('total')[:1]
        )
        qs = qs.annotate(item_count=Subquery(item_count, output_field=IntegerField()))

        params = self.request.query_params

        # Date range. Unlike OrderListView, end_date is honoured on its own.
        start_date = params.get('start_date')
        end_date = params.get('end_date')
        if start_date:
            qs = qs.filter(created__gte=timezone.make_aware(
                datetime.strptime(start_date, '%Y-%m-%d')))
        if end_date:
            qs = qs.filter(created__lt=timezone.make_aware(
                datetime.strptime(end_date, '%Y-%m-%d')) + timedelta(days=1))

        status_param = params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        search = params.get('search')
        if search:
            qs = qs.filter(
                Q(order_id__icontains=search)
                | Q(checkout_session__email__icontains=search)
                | Q(tracking_number__icontains=search)
                | Q(checkout_session__shipping_address__first_name__icontains=search)
                | Q(checkout_session__shipping_address__last_name__icontains=search)
            )

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
            .select_related(*ORDER_SELECT_RELATED)
            .prefetch_related(*ORDER_PREFETCH_RELATED)
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
                    F('checkout_session__cart__items__product__current_price'),
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
    Returns:
        { "all_sold": <int> }
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        SOURCE_ECOMMERCE_V2 = 1

        # 1) Historical total across ALL sources
        historical_total = UnitsSold.objects.aggregate(
            total=Sum('units_sold')
        )['total'] or 0

        # 2) Last recorded ecommerce v2 day
        last_ecom_date = (
            UnitsSold.objects
            .filter(source_fk_id=SOURCE_ECOMMERCE_V2)
            .aggregate(d=Max('date'))
        )['d']

        if last_ecom_date is None:
            return Response(
                {"detail": "No UnitsSold rows for ecommerce v2. Backfill required."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Start strictly AFTER the last recorded day to avoid double counting
        start_date = last_ecom_date + timedelta(days=1)
        start_dt = timezone.make_aware(datetime.combine(start_date, time.min))

        # 3) Live increment: paid ecommerce v2 carts from start_date..today
        paid_orders = (
            Order.objects
            .filter(
                checkout_session__payment_status='paid',
                created__gte=start_dt
            )
            .values_list('checkout_session__cart_id', flat=True)
        )
        cart_ids = [cid for cid in paid_orders if cid]

        units_expr = ExpressionWrapper(
            F('product__units_per_box') * F('quantity'),
            output_field=IntegerField()
        )
        live_increment = (
            CartItem.objects
            .filter(cart_id__in=cart_ids)
            .aggregate(units=Sum(units_expr))
        )['units'] or 0

        all_sold = historical_total + live_increment
        return Response({"all_sold": all_sold})
