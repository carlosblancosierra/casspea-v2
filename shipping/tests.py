from decimal import Decimal

from django.test import TestCase, override_settings

from .models import ShippingOption


@override_settings(SHIPPING_DISCOUNT_THRESHOLD=55, SHIPPING_DISCOUNT_AMOUNT='5.00')
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
        pricing = self._option('5.99').pricing_for_cart_total(Decimal('54.99'))
        self.assertEqual(pricing['discounted_price'], Decimal('5.99'))
        self.assertEqual(pricing['discounted_cents'], 599)
        self.assertEqual(pricing['discount_amount'], Decimal('0.00'))

    def test_discount_applied_at_threshold(self):
        pricing = self._option('5.99').pricing_for_cart_total(Decimal('55.00'))
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
        for total in (None, Decimal('0'), Decimal('54.99'), Decimal('55.00'), Decimal('120.00')):
            pricing = option.pricing_for_cart_total(total)
            self.assertEqual(
                pricing['discounted_cents'],
                int((pricing['discounted_price'] * 100).to_integral_value()),
                msg=f'mismatch at cart total {total}',
            )


class GuaranteedFlagTests(TestCase):
    """The checkout words guaranteed services differently from estimates, so
    the flag has to mean what it says. Most orders here are gifts for a fixed
    date; calling an estimate a guarantee is the expensive kind of wrong."""

    fixtures = ['initial_shipping.json']

    def test_only_special_delivery_is_guaranteed(self):
        guaranteed = ShippingOption.objects.filter(guaranteed=True)

        self.assertEqual([o.name for o in guaranteed], ['Next Day Guaranteed'])

    def test_tracked_services_are_estimates(self):
        for name in ('Priority 24', 'Regular 48'):
            with self.subTest(option=name):
                self.assertFalse(ShippingOption.objects.get(name=name).guaranteed)

    def test_new_options_are_not_guaranteed_unless_said_so(self):
        option = ShippingOption.objects.create(
            company_id=1,
            name='Some new service',
            delivery_speed='REGULAR',
            price=Decimal('4.00'),
            estimated_days_min=2,
            estimated_days_max=3,
        )

        self.assertFalse(option.guaranteed)
