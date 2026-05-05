from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Prefetch
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from carts.models import CartItem
from orders.models import Order
from users.authentication import CustomJWTAuthentication
from .models import Discount


class DiscountStatsView(APIView):
    """
    GET /api/discounts/stats/
    Returns usage stats per discount code: carts applied, paid orders, and total revenue.
    """
    permission_classes = [permissions.IsAdminUser]
    authentication_classes = [CustomJWTAuthentication]

    def get(self, request):
        discounts = (
            Discount.objects
            .annotate(cart_count=Count('cart', distinct=True))
            .prefetch_related('exclusions')
            .order_by('-created')
        )

        paid_orders = (
            Order.objects
            .filter(
                checkout_session__payment_status='paid',
                checkout_session__cart__discount__isnull=False,
            )
            .select_related(
                'checkout_session__cart__discount',
                'checkout_session__shipping_option',
            )
            .prefetch_related(
                Prefetch(
                    'checkout_session__cart__items',
                    queryset=CartItem.objects.select_related('product'),
                ),
                'checkout_session__cart__discount__exclusions',
            )
        )

        discount_totals = defaultdict(Decimal)
        discount_order_counts = defaultdict(int)

        for order in paid_orders:
            cart = order.checkout_session.cart
            discount = cart.discount
            if not discount:
                continue

            items = list(cart.items.all())
            base_total = sum(item.base_price for item in items)

            if discount.discount_type == Discount.PERCENTAGE:
                excluded = set(discount.exclusions.all())
                non_excluded = sum(
                    item.base_price for item in items
                    if item.product not in excluded
                )
                cart_total = max(
                    base_total - (non_excluded * discount.amount / 100),
                    Decimal('0'),
                )
            else:
                cart_total = max(base_total - discount.amount, Decimal('0'))

            shipping = Decimal('0')
            if order.checkout_session.shipping_option:
                base_shipping = Decimal(order.checkout_session.shipping_option.cents) / 100
                threshold = Decimal(str(getattr(settings, 'SHIPPING_DISCOUNT_THRESHOLD', 50)))
                if cart_total >= threshold:
                    base_shipping = max(base_shipping - Decimal('4.99'), Decimal('0'))
                shipping = base_shipping

            discount_totals[discount.id] += (cart_total + shipping).quantize(Decimal('0.01'))
            discount_order_counts[discount.id] += 1

        result = [
            {
                'title': d.title,
                'code': d.code,
                'amount': d.amount,
                'discount_type': d.discount_type,
                'active': d.active,
                'carts': d.cart_count,
                'orders': discount_order_counts.get(d.id, 0),
                'orders_total': discount_totals.get(d.id, Decimal('0.00')),
            }
            for d in discounts
        ]

        return Response(result)
