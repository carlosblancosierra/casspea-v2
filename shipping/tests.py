from decimal import Decimal

from django.test import TestCase, override_settings

from .models import ShippingOption


@override_settings(SHIPPING_DISCOUNT_THRESHOLD=60, SHIPPING_DISCOUNT_AMOUNT='5.00')
class ShippingOptionPricingTests(TestCase):
    """The displayed price and the charged price both come from
    ``pricing_for_cart_total``; these tests guard that they stay in sync."""

    def _option(self, price='5.99'):
        # No DB write needed: pricing_for_cart_total only reads ``price``.
        return ShippingOption(
            name='Priority',
            delivery_speed='PRIORITY',
            price=Decimal(price),
            cents=599,
            estimated_days_min=1,
            estimated_days_max=1,
        )

    def test_no_discount_below_threshold(self):
        pricing = self._option('5.99').pricing_for_cart_total(Decimal('59.99'))
        self.assertEqual(pricing['discounted_price'], Decimal('5.99'))
        self.assertEqual(pricing['discounted_cents'], 599)
        self.assertEqual(pricing['discount_amount'], Decimal('0.00'))

    def test_discount_applied_at_threshold(self):
        pricing = self._option('5.99').pricing_for_cart_total(Decimal('60.00'))
        self.assertEqual(pricing['discounted_price'], Decimal('0.99'))
        self.assertEqual(pricing['discounted_cents'], 99)
        self.assertEqual(pricing['discount_amount'], Decimal('5.00'))

    def test_discount_applied_above_threshold(self):
        pricing = self._option('5.99').pricing_for_cart_total(Decimal('75.00'))
        self.assertEqual(pricing['discounted_cents'], 99)

    def test_no_cart_total_means_no_discount(self):
        pricing = self._option('5.99').pricing_for_cart_total(None)
        self.assertEqual(pricing['discounted_cents'], 599)

    def test_discount_never_goes_negative(self):
        pricing = self._option('3.99').pricing_for_cart_total(Decimal('60.00'))
        self.assertEqual(pricing['discounted_price'], Decimal('0.00'))
        self.assertEqual(pricing['discounted_cents'], 0)

    def test_displayed_pounds_and_charged_cents_always_agree(self):
        # This is the regression: what we show (pounds) must equal what we
        # charge (cents) for every cart total around the threshold.
        option = self._option('5.99')
        for total in (None, Decimal('0'), Decimal('59.99'), Decimal('60.00'), Decimal('120.00')):
            pricing = option.pricing_for_cart_total(total)
            self.assertEqual(
                pricing['discounted_cents'],
                int((pricing['discounted_price'] * 100).to_integral_value()),
                msg=f'mismatch at cart total {total}',
            )
