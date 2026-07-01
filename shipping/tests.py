import datetime
from decimal import Decimal

from django.test import TestCase, override_settings

from .models import ShippingOption, is_summer_shipping


@override_settings(
    SHIPPING_DISCOUNT_THRESHOLD=60,
    SHIPPING_DISCOUNT_AMOUNT='5.00',
    SUMMER_SHIPPING_MONTHS=(),  # force off-season so these tests don't depend on the run date
)
class ShippingOptionPricingTests(TestCase):
    """Off-season pricing. The displayed price and the charged price both come
    from ``pricing_for_cart_total``; these tests guard that they stay in sync."""

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


@override_settings(
    SHIPPING_DISCOUNT_THRESHOLD=60,
    SUMMER_SHIPPING_MONTHS=tuple(range(1, 13)),  # force summer so these tests don't depend on the run date
    SUMMER_ICE_PACK_SURCHARGE='1.00',
    SUMMER_SHIPPING_DISCOUNT_AMOUNT='6.00',
)
class SummerShippingPricingTests(TestCase):
    """Summer ice-pack season: every option costs £1 more, and the over-threshold
    discount is £6, so standard delivery is free over the threshold."""

    def _option(self, price, cents):
        return ShippingOption(
            name='Option',
            delivery_speed='PRIORITY',
            price=Decimal(price),
            cents=cents,
            estimated_days_min=1,
            estimated_days_max=1,
        )

    def test_surcharge_applied_below_threshold(self):
        # Priority £4.99 base -> £5.99 in summer; no discount under £60.
        pricing = self._option('4.99', 499).pricing_for_cart_total(Decimal('59.99'))
        self.assertEqual(pricing['original_price'], Decimal('5.99'))
        self.assertEqual(pricing['discounted_price'], Decimal('5.99'))
        self.assertEqual(pricing['discounted_cents'], 599)

    def test_standard_priority_free_over_threshold(self):
        # Priority £4.99 -> £5.99, minus £6 -> free over £60.
        pricing = self._option('4.99', 499).pricing_for_cart_total(Decimal('60.00'))
        self.assertEqual(pricing['original_price'], Decimal('5.99'))
        self.assertEqual(pricing['discounted_price'], Decimal('0.00'))
        self.assertEqual(pricing['discounted_cents'], 0)

    def test_standard_regular_free_over_threshold(self):
        # Regular £3.99 -> £4.99, minus £6 -> free over £60.
        pricing = self._option('3.99', 399).pricing_for_cart_total(Decimal('60.00'))
        self.assertEqual(pricing['original_price'], Decimal('4.99'))
        self.assertEqual(pricing['discounted_price'], Decimal('0.00'))
        self.assertEqual(pricing['discounted_cents'], 0)

    def test_next_day_not_free_over_threshold(self):
        # Next Day £11.99 -> £12.99, minus £6 -> £6.99 over £60 (not free).
        pricing = self._option('11.99', 1199).pricing_for_cart_total(Decimal('60.00'))
        self.assertEqual(pricing['original_price'], Decimal('12.99'))
        self.assertEqual(pricing['discounted_price'], Decimal('6.99'))
        self.assertEqual(pricing['discounted_cents'], 699)

    def test_displayed_pounds_and_charged_cents_always_agree(self):
        option = self._option('4.99', 499)
        for total in (None, Decimal('0'), Decimal('59.99'), Decimal('60.00'), Decimal('120.00')):
            pricing = option.pricing_for_cart_total(total)
            self.assertEqual(
                pricing['discounted_cents'],
                int((pricing['discounted_price'] * 100).to_integral_value()),
                msg=f'mismatch at cart total {total}',
            )


class IsSummerShippingTests(TestCase):
    @override_settings(SUMMER_SHIPPING_MONTHS=(6, 7, 8, 9))
    def test_summer_months(self):
        self.assertTrue(is_summer_shipping(datetime.date(2026, 6, 1)))
        self.assertTrue(is_summer_shipping(datetime.date(2026, 7, 1)))
        self.assertTrue(is_summer_shipping(datetime.date(2026, 9, 30)))

    @override_settings(SUMMER_SHIPPING_MONTHS=(6, 7, 8, 9))
    def test_non_summer_months(self):
        self.assertFalse(is_summer_shipping(datetime.date(2026, 5, 31)))
        self.assertFalse(is_summer_shipping(datetime.date(2026, 10, 1)))
        self.assertFalse(is_summer_shipping(datetime.date(2026, 1, 15)))
