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


class EstimateRangeTests(TestCase):
    """
    A service the carrier describes as a range must be stored as a range.

    Every option used to have estimated_days_min == estimated_days_max, so the
    checkout printed a single delivery date for Tracked 24 and Tracked 48 —
    a promise neither we nor Royal Mail have made. Only Special Delivery is
    sold as one guaranteed day.
    """

    fixtures = ['initial_shipping.json']

    def test_estimated_services_span_more_than_one_day(self):
        for name in ('Priority 24', 'Regular 48'):
            with self.subTest(option=name):
                option = ShippingOption.objects.get(name=name)
                self.assertGreater(
                    option.estimated_days_max,
                    option.estimated_days_min,
                    f'{name} is an estimate, so it cannot claim a single delivery day',
                )

    def test_the_guaranteed_service_is_a_single_day(self):
        option = ShippingOption.objects.get(name='Next Day Guaranteed')

        self.assertEqual(option.estimated_days_min, option.estimated_days_max)

    def test_every_estimate_is_a_range_and_every_range_is_an_estimate(self):
        """The two fields have to agree: a single-day option is exactly the
        one the carrier guarantees."""
        for option in ShippingOption.objects.all():
            with self.subTest(option=option.name):
                is_single_day = option.estimated_days_min == option.estimated_days_max
                self.assertEqual(is_single_day, option.guaranteed)


class WidenEstimateRangesMigrationTests(TestCase):
    """
    The fixture is already correct, so it cannot prove the migration fixes a
    live database — which is the only place the bad data actually is. This
    puts the rows back the way production holds them and runs the migration's
    own function over them.
    """

    fixtures = ['initial_shipping.json']

    def setUp(self):
        # Reintroduce the bug: every option claiming a single delivery day.
        for option in ShippingOption.objects.all():
            option.estimated_days_max = option.estimated_days_min
            option.save(update_fields=['estimated_days_max'])

    def _run_migration(self):
        from importlib import import_module
        from django.apps import apps
        # The module name starts with a digit, so it cannot be imported with
        # a plain import statement.
        module = import_module('shipping.migrations.0007_widen_estimate_ranges')
        module.widen_estimate_ranges(apps, None)

    def test_widens_the_estimated_services(self):
        self._run_migration()

        self.assertEqual(ShippingOption.objects.get(name='Priority 24').estimated_days_max, 2)
        self.assertEqual(ShippingOption.objects.get(name='Regular 48').estimated_days_max, 3)

    def test_leaves_the_guaranteed_service_as_a_single_day(self):
        self._run_migration()

        option = ShippingOption.objects.get(name='Next Day Guaranteed')
        self.assertEqual(option.estimated_days_min, option.estimated_days_max)

    def test_does_not_widen_a_range_someone_already_set(self):
        already = ShippingOption.objects.get(name='Regular 48')
        already.estimated_days_max = 5
        already.save(update_fields=['estimated_days_max'])

        self._run_migration()

        self.assertEqual(ShippingOption.objects.get(name='Regular 48').estimated_days_max, 5)


class OfferedOptionsTests(TestCase):
    """
    Two options, not three.

    Priority 24 sat between the tracked service and Special Delivery — dearer
    than one, without the guarantee of the other — so it was a third column of
    near-identical text to compare and no real third answer.
    """

    fixtures = ['initial_shipping.json']

    def test_only_two_options_are_offered(self):
        offered = ShippingOption.objects.filter(active=True).order_by('price')

        self.assertEqual([o.name for o in offered], ['Regular 48', 'Next Day Guaranteed'])

    def test_the_retired_option_is_kept_not_deleted(self):
        """Every order ever placed with it points at this row, and that FK is
        SET_NULL — deleting it would erase what those customers paid for."""
        retired = ShippingOption.objects.get(name='Priority 24')

        self.assertFalse(retired.active)

    def test_the_two_offered_options_are_a_real_choice(self):
        """One is a range and cheap, the other is a guaranteed date. If both
        were the same shape the customer would be picking on price alone."""
        tracked = ShippingOption.objects.get(name='Regular 48')
        guaranteed = ShippingOption.objects.get(name='Next Day Guaranteed')

        self.assertFalse(tracked.guaranteed)
        self.assertGreater(tracked.estimated_days_max, tracked.estimated_days_min)
        self.assertTrue(guaranteed.guaranteed)
        self.assertEqual(guaranteed.estimated_days_min, guaranteed.estimated_days_max)
        self.assertLess(tracked.price, guaranteed.price)


@override_settings(SHIPPING_DISCOUNT_THRESHOLD=56, SHIPPING_DISCOUNT_AMOUNT='6.00')
class FreeDeliveryThresholdTests(TestCase):
    """
    £6 off over £56, chosen so the tracked option lands at exactly free.

    A threshold only works as an incentive if the reward is legible. "Free
    delivery" is; "£3.99 becomes 99p off" is not.
    """

    fixtures = ['initial_shipping.json']

    def test_tracked_delivery_is_free_over_the_threshold(self):
        tracked = ShippingOption.objects.get(name='Regular 48')

        pricing = tracked.pricing_for_cart_total(Decimal('56.00'))

        self.assertEqual(pricing['discounted_price'], Decimal('0.00'))
        self.assertEqual(pricing['discounted_cents'], 0)

    def test_the_guaranteed_option_is_discounted_by_the_same_amount(self):
        guaranteed = ShippingOption.objects.get(name='Next Day Guaranteed')

        pricing = guaranteed.pricing_for_cart_total(Decimal('56.00'))

        self.assertEqual(pricing['discounted_price'], Decimal('5.99'))

    def test_a_penny_under_the_threshold_pays_full_price(self):
        tracked = ShippingOption.objects.get(name='Regular 48')

        pricing = tracked.pricing_for_cart_total(Decimal('55.99'))

        self.assertEqual(pricing['discounted_price'], Decimal('3.99'))

    def test_the_discount_never_goes_negative(self):
        """A £3.99 option minus £6 is free, not a 2.01 credit."""
        tracked = ShippingOption.objects.get(name='Regular 48')

        pricing = tracked.pricing_for_cart_total(Decimal('500.00'))

        self.assertEqual(pricing['discounted_price'], Decimal('0.00'))


class FlagGuaranteedMigrationTests(TestCase):
    """
    The fixture already ships guaranteed=True, so it cannot prove the
    migration fixes a live database — which is the only place the flag is
    still False. This puts the rows back the way production holds them after
    0006 and runs the migration's own function over them.
    """

    fixtures = ['initial_shipping.json']

    def setUp(self):
        # Reintroduce the state 0006 leaves behind: the field exists and
        # nothing is flagged.
        ShippingOption.objects.update(guaranteed=False)

    def _run_migration(self):
        from importlib import import_module
        from django.apps import apps
        module = import_module('shipping.migrations.0009_flag_special_delivery_guaranteed')
        module.flag_guaranteed_services(apps, None)

    def test_flags_the_next_day_service(self):
        self._run_migration()

        self.assertTrue(ShippingOption.objects.get(name='Next Day Guaranteed').guaranteed)

    def test_leaves_the_tracked_services_as_estimates(self):
        """Flagging everything would be worse than flagging nothing: it would
        turn every estimate into a promise the carrier has not made."""
        self._run_migration()

        for name in ('Priority 24', 'Regular 48'):
            with self.subTest(option=name):
                self.assertFalse(ShippingOption.objects.get(name=name).guaranteed)

    def test_matches_on_speed_rather_than_name(self):
        """The name is editable in admin; renaming the service must not
        silently turn its guarantee back into an estimate."""
        option = ShippingOption.objects.get(delivery_speed='NEXT_DAY')
        option.name = 'Special Delivery Guaranteed by 1pm'
        option.save(update_fields=['name'])

        self._run_migration()

        option.refresh_from_db()
        self.assertTrue(option.guaranteed)
