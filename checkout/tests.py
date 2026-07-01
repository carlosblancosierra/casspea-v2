"""Tests for checkout pricing and the Stripe payload.

These guard the invariant that what the customer sees in the cart is what
Stripe charges: shipping cost, cart discount and sold-out handling.
"""
from decimal import Decimal

from django.test import TestCase, override_settings

from carts.models import Cart, CartItem
from carts.tests.test_totals import make_product
from discounts.models import Discount
from shipping.models import ShippingCompany, ShippingOption

from .models import CheckoutSession
from .stripe_utils import prepare_stripe_payload


def make_shipping_option(price='5.99'):
    company, _ = ShippingCompany.objects.get_or_create(
        code='test-courier', defaults={'name': 'Test Courier'}
    )
    return ShippingOption.objects.create(
        company=company,
        name='Tracked 24',
        delivery_speed='PRIORITY',
        price=Decimal(price),
        estimated_days_min=1,
        estimated_days_max=2,
    )


@override_settings(SHIPPING_DISCOUNT_THRESHOLD=55, SHIPPING_DISCOUNT_AMOUNT='5.00')
class CheckoutSessionPricingTest(TestCase):
    def setUp(self):
        self.cart = Cart.objects.create(session_id='test-session')
        self.box = make_product('Box of 9', '14.99')
        self.option = make_shipping_option('5.99')

    def add_items(self, quantity):
        CartItem.objects.create(cart=self.cart, product=self.box, quantity=quantity)

    def make_session(self, **kwargs):
        return CheckoutSession.objects.create(
            cart=self.cart, email='guest@example.com', **kwargs
        )

    def test_guest_checkout_requires_email(self):
        with self.assertRaises(ValueError):
            CheckoutSession.objects.create(cart=self.cart)

    def test_shipping_cost_zero_without_option(self):
        session = self.make_session()
        self.assertEqual(session.shipping_cost, 0)
        self.assertEqual(session.shipping_cost_pounds, Decimal('0.00'))

    def test_shipping_cost_below_threshold_is_full_price(self):
        self.add_items(1)  # 14.99 < 55
        session = self.make_session(shipping_option=self.option)

        self.assertEqual(session.shipping_cost, 599)
        self.assertEqual(session.shipping_cost_pounds, Decimal('5.99'))

    def test_shipping_cost_above_threshold_gets_discount(self):
        self.add_items(4)  # 59.96 >= 55
        session = self.make_session(shipping_option=self.option)

        self.assertEqual(session.shipping_cost, 99)  # 5.99 - 5.00
        self.assertEqual(session.shipping_cost_pounds, Decimal('0.99'))

    def test_total_with_shipping(self):
        self.add_items(1)
        session = self.make_session(shipping_option=self.option)

        self.assertEqual(session.total_with_shipping, Decimal('20.98'))

    def test_shipping_stripe_format_matches_displayed_price(self):
        self.add_items(4)
        session = self.make_session(shipping_option=self.option)

        data = session.shipping_stripe_format['shipping_rate_data']
        self.assertEqual(data['fixed_amount']['amount'], 99)
        self.assertEqual(data['fixed_amount']['currency'], 'gbp')
        self.assertEqual(data['display_name'], 'Tracked 24')


@override_settings(SHIPPING_DISCOUNT_THRESHOLD=55, SHIPPING_DISCOUNT_AMOUNT='5.00')
class StripePayloadTest(TestCase):
    def setUp(self):
        self.cart = Cart.objects.create(session_id='test-session')
        self.box = make_product('Box of 9', '14.99')
        self.option = make_shipping_option()
        CartItem.objects.create(cart=self.cart, product=self.box, quantity=2)
        self.session = CheckoutSession.objects.create(
            cart=self.cart, email='guest@example.com', shipping_option=self.option
        )

    def test_payload_includes_line_items_and_email(self):
        payload = prepare_stripe_payload(self.session)

        self.assertEqual(len(payload['line_items']), 1)
        self.assertEqual(payload['line_items'][0]['quantity'], 2)
        self.assertEqual(payload['customer_email'], 'guest@example.com')
        self.assertEqual(payload['mode'], 'payment')
        self.assertIn('success_url', payload)
        self.assertNotIn('ui_mode', payload)

    def test_embedded_payload_uses_return_url(self):
        payload = prepare_stripe_payload(self.session, embedded=True)

        self.assertEqual(payload['ui_mode'], 'embedded')
        self.assertIn('return_url', payload)
        self.assertNotIn('success_url', payload)

    def test_sold_out_items_are_excluded(self):
        self.box.sold_out = True
        self.box.save()

        with self.assertRaises(ValueError):
            prepare_stripe_payload(self.session)

    def test_valid_discount_is_sent_to_stripe(self):
        discount = Discount.objects.create(
            title='10% off', code='TEN', stripe_id='stripe_TEN',
            discount_type=Discount.PERCENTAGE, amount=Decimal('10.00'), active=True,
        )
        self.cart.discount = discount
        self.cart.save()

        payload = prepare_stripe_payload(self.session)
        self.assertEqual(payload['discounts'], [{'coupon': 'stripe_TEN'}])

    def test_discount_below_min_order_is_not_sent_to_stripe(self):
        """Stripe must not apply a coupon the cart totals refused."""
        discount = Discount.objects.create(
            title='Big spender', code='BIG', stripe_id='stripe_BIG',
            discount_type=Discount.PERCENTAGE, amount=Decimal('20.00'),
            active=True, min_order_value=55,
        )
        self.cart.discount = discount
        self.cart.save()

        payload = prepare_stripe_payload(self.session)  # cart total 29.98 < 55
        self.assertEqual(payload['discounts'], [])

    def test_inactive_discount_is_not_sent_to_stripe(self):
        discount = Discount.objects.create(
            title='Off', code='OFF', stripe_id='stripe_OFF',
            discount_type=Discount.PERCENTAGE, amount=Decimal('10.00'), active=False,
        )
        self.cart.discount = discount
        self.cart.save()

        payload = prepare_stripe_payload(self.session)
        self.assertEqual(payload['discounts'], [])
