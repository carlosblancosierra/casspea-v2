"""Unit tests for cart pricing: base totals, percentage and fixed discounts,
exclusions and the minimum-order-value rule. These are the numbers the
customer sees in the cart and the amounts Stripe charges, so they are the
most important calculations in the shop."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from carts.models import Cart, CartItem
from discounts.models import Discount
from products.models import Product, ProductCategory


def make_product(name, price, **kwargs):
    category, _ = ProductCategory.objects.get_or_create(
        slug='test-category',
        defaults={'name': 'Test Category', 'description': 'x'},
    )
    return Product.objects.create(
        name=name,
        description='x',
        category=category,
        base_price=Decimal(price),
        stripe_price_id=f'price_{name}',
        slug=name.lower().replace(' ', '-'),
        weight=100,
        units_per_box=9,
        main_color='red',
        secondary_color='blue',
        seo_title=name,
        seo_description=name,
        **kwargs,
    )


class CartTotalsTest(TestCase):
    def setUp(self):
        self.cart = Cart.objects.create(session_id='test-session')
        self.box = make_product('Box of 9', '14.99')
        self.big_box = make_product('Box of 48', '74.99')

    def add(self, product, quantity=1):
        return CartItem.objects.create(cart=self.cart, product=product, quantity=quantity)

    def apply_discount(self, **kwargs):
        defaults = {
            'title': 'Test discount',
            'code': 'TEST',
            'stripe_id': 'TEST',
            'discount_type': Discount.PERCENTAGE,
            'amount': Decimal('10.00'),
            'active': True,
        }
        defaults.update(kwargs)
        discount = Discount.objects.create(**defaults)
        self.cart.discount = discount
        self.cart.save()
        return discount

    def test_base_total_sums_items(self):
        self.add(self.box, quantity=2)
        self.add(self.big_box)
        self.assertEqual(self.cart.base_total, Decimal('104.97'))

    def test_no_discount_means_no_savings(self):
        self.add(self.box)
        self.assertEqual(self.cart.discounted_total, Decimal('14.99'))
        self.assertEqual(self.cart.total_savings, Decimal('0.00'))
        self.assertFalse(self.cart.is_discount_valid)

    def test_percentage_discount(self):
        self.add(self.box, quantity=2)  # 29.98
        self.apply_discount(amount=Decimal('10.00'))

        self.assertTrue(self.cart.is_discount_valid)
        self.assertEqual(self.cart.discounted_total, Decimal('26.982'))
        self.assertEqual(self.cart.total_savings, Decimal('3.00'))

    def test_percentage_discount_skips_excluded_products(self):
        self.add(self.box)      # 14.99, excluded
        self.add(self.big_box)  # 74.99
        discount = self.apply_discount(amount=Decimal('10.00'))
        discount.exclusions.add(self.box)

        # Only the big box is discounted: 89.98 - 7.499 = 82.481
        self.assertEqual(self.cart.discounted_total, Decimal('82.481'))

    def test_fixed_amount_discount(self):
        self.add(self.box, quantity=4)  # 59.96
        self.apply_discount(
            discount_type=Discount.FIXED_AMOUNT, amount=Decimal('5.00')
        )

        self.assertEqual(self.cart.discounted_total, Decimal('54.96'))
        self.assertEqual(self.cart.total_savings, Decimal('5.00'))

    def test_fixed_amount_discount_never_goes_negative(self):
        self.add(self.box)  # 14.99
        self.apply_discount(
            discount_type=Discount.FIXED_AMOUNT, amount=Decimal('20.00')
        )

        self.assertEqual(self.cart.discounted_total, 0)

    def test_fixed_amount_item_price_stays_unchanged(self):
        """Fixed-amount discounts apply to the cart, not per item, and the
        item serializer must never see None here (regression test)."""
        item = self.add(self.box)
        self.apply_discount(
            discount_type=Discount.FIXED_AMOUNT, amount=Decimal('5.00')
        )

        self.assertEqual(item.discounted_price, Decimal('14.99'))
        self.assertEqual(item.savings, 0)

    def test_percentage_item_price(self):
        item = self.add(self.box, quantity=2)  # 29.98
        self.apply_discount(amount=Decimal('10.00'))

        self.assertEqual(item.discounted_price, Decimal('26.982'))
        self.assertEqual(item.savings, Decimal('2.998'))

    def test_expired_discount_is_not_applied(self):
        self.add(self.box)
        self.apply_discount(end_date=timezone.now() - timedelta(days=1))

        self.assertFalse(self.cart.is_discount_valid)
        self.assertEqual(self.cart.discounted_total, Decimal('14.99'))
        self.assertEqual(self.cart.total_savings, Decimal('0.00'))

    def test_inactive_discount_is_not_applied(self):
        self.add(self.box)
        self.apply_discount(active=False)

        self.assertFalse(self.cart.is_discount_valid)
        self.assertEqual(self.cart.discounted_total, Decimal('14.99'))

    def test_discount_below_min_order_value_is_not_applied(self):
        """If items are removed and the cart drops under the minimum, the
        discount stops applying instead of silently understating the total."""
        self.add(self.box)  # 14.99 < 55 minimum
        self.apply_discount(amount=Decimal('20.00'), min_order_value=55)

        self.assertFalse(self.cart.is_discount_valid)
        self.assertEqual(self.cart.discounted_total, Decimal('14.99'))
        self.assertEqual(self.cart.total_savings, Decimal('0.00'))

    def test_discount_applies_once_min_order_value_met(self):
        self.add(self.box, quantity=4)  # 59.96 >= 55
        self.apply_discount(amount=Decimal('20.00'), min_order_value=55)

        self.assertTrue(self.cart.is_discount_valid)
        self.assertEqual(self.cart.total_savings, Decimal('12.00'))

    def test_preorder_price_used_when_active(self):
        preorder = make_product(
            'Preorder Box', '30.00',
            preorder=True,
            preorder_price=Decimal('25.00'),
            preorder_finish_date=(timezone.now() + timedelta(days=10)).date(),
        )
        self.add(preorder)

        self.assertEqual(self.cart.base_total, Decimal('25.00'))
