"""Tests for checkout pricing and the Stripe payload.

These guard the invariant that what the customer sees in the cart is what
Stripe charges: shipping cost, cart discount and sold-out handling.
"""
from decimal import Decimal
from unittest import mock

import stripe
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, override_settings

from orders.models import Order

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

    def test_payload_does_not_send_payment_method_types(self):
        """Stripe removed it from Checkout Session creation and now answers 400.

        The methods on offer come from the Dashboard's payment-method settings.
        """
        self.assertNotIn('payment_method_types', prepare_stripe_payload(self.session))
        self.assertNotIn(
            'payment_method_types', prepare_stripe_payload(self.session, embedded=True)
        )

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


class StripeWebhookTest(TestCase):
    """The webhook is where money becomes an order: it must be idempotent,
    create the order, mark the session paid and retire the cart."""

    def setUp(self):
        self.cart = Cart.objects.create(session_id='test-session')
        self.box = make_product('Box of 9', '14.99')
        CartItem.objects.create(cart=self.cart, product=self.box, quantity=2)
        self.session = CheckoutSession.objects.create(
            cart=self.cart, email='guest@example.com'
        )

    def _event(self):
        """Fake checkout.session.completed event as construct_event returns."""
        stripe_session = mock.Mock()
        stripe_session.id = 'cs_test_123'
        stripe_session.payment_intent = 'pi_test_123'
        stripe_session.metadata = {'checkout_session_id': str(self.session.id)}

        event = mock.MagicMock()
        event.id = 'evt_test_123'
        event.type = 'checkout.session.completed'
        event.__getitem__.side_effect = lambda key: {
            'type': 'checkout.session.completed',
            'data': {'object': stripe_session},
        }[key]
        return event

    def _line_items(self):
        """Stripe line items matching the cart exactly (no reconciliation)."""
        item = mock.Mock()
        item.price.id = self.box.stripe_price_id
        item.quantity = 2
        result = mock.Mock()
        result.auto_paging_iter.return_value = iter([item])
        return result

    def _post(self):
        return self.client.post(
            '/api/checkout/stripe/webhook/',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='t=1,v1=sig',
        )

    def test_invalid_signature_returns_400(self):
        with mock.patch(
            'checkout.webhooks.stripe.Webhook.construct_event',
            side_effect=stripe.error.SignatureVerificationError('bad', 'sig'),
        ):
            response = self._post()
        self.assertEqual(response.status_code, 400)

    def test_completed_session_creates_order_and_marks_paid(self):
        with mock.patch(
            'checkout.webhooks.stripe.Webhook.construct_event',
            return_value=self._event(),
        ), mock.patch(
            'checkout.webhooks.stripe.checkout.Session.list_line_items',
            return_value=self._line_items(),
        ):
            response = self._post()

        self.assertEqual(response.status_code, 200)

        self.session.refresh_from_db()
        self.cart.refresh_from_db()
        self.assertEqual(self.session.payment_status, CheckoutSession.Status.PAID)
        self.assertEqual(self.session.stripe_payment_intent, 'pi_test_123')
        self.assertFalse(self.cart.active)
        self.assertTrue(Order.objects.filter(checkout_session=self.session).exists())

    def test_webhook_is_idempotent(self):
        """A Stripe retry for an already-paid session must not duplicate orders."""
        with mock.patch(
            'checkout.webhooks.stripe.Webhook.construct_event',
            return_value=self._event(),
        ), mock.patch(
            'checkout.webhooks.stripe.checkout.Session.list_line_items',
            return_value=self._line_items(),
        ):
            first = self._post()
            second = self._post()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            Order.objects.filter(checkout_session=self.session).count(), 1
        )

    def test_unknown_checkout_session_returns_404(self):
        event = self._event()  # capture the session id before deleting
        self.session.delete()
        with mock.patch(
            'checkout.webhooks.stripe.Webhook.construct_event',
            return_value=event,
        ):
            response = self._post()
        self.assertEqual(response.status_code, 404)

    def test_reconciliation_updates_quantity_to_match_stripe(self):
        """If Stripe charged a different quantity, the cart follows Stripe."""
        line_items = self._line_items()
        item = mock.Mock()
        item.price.id = self.box.stripe_price_id
        item.quantity = 3  # Stripe charged 3, cart says 2
        line_items.auto_paging_iter.return_value = iter([item])

        with mock.patch(
            'checkout.webhooks.stripe.Webhook.construct_event',
            return_value=self._event(),
        ), mock.patch(
            'checkout.webhooks.stripe.checkout.Session.list_line_items',
            return_value=line_items,
        ):
            response = self._post()

        self.assertEqual(response.status_code, 200)
        cart_item = self.cart.items.get()
        self.assertEqual(cart_item.quantity, 3)


class FixedDispatchBlocksPickupTest(TestCase):
    """A batch posted on a named day is the opposite of coming to fetch it.

    The checkout does not offer collection for such a cart, but a control the UI
    hides is not a rule. These tests are about the rule.
    """

    def setUp(self):
        from datetime import timedelta
        from django.utils import timezone

        self.cart = Cart.objects.create(session_id='fixed-dispatch-session')
        self.calendar = make_product('Advent Calendar', '49.99')
        self.calendar.fixed_dispatch_date = timezone.localdate() + timedelta(days=30)
        self.calendar.save(update_fields=['fixed_dispatch_date'])
        self.box = make_product('Box of 9', '14.99')

        company, _ = ShippingCompany.objects.get_or_create(
            code='test-courier', defaults={'name': 'Test Courier'}
        )
        self.pickup = ShippingOption.objects.create(
            company=company,
            name='Store pickup',
            delivery_speed='PICKUP',
            price=Decimal('0.00'),
            estimated_days_min=0,
            estimated_days_max=0,
        )
        self.shipping = make_shipping_option('5.99')

    def accepts(self, option):
        """Put the real serializer through its real validate().

        Reimplementing the rule here would produce a test that passes while the
        serializer is broken, so this builds what it needs instead: a request
        carrying the cart's session, and an address owned by that session, since
        the address checks run before the one under test.
        """
        from rest_framework.test import APIRequestFactory
        from django.contrib.sessions.backends.db import SessionStore

        from addresses.models import Address
        from checkout.serializers import CheckoutDetailsSerializer

        store = SessionStore()
        store.create()
        self.cart.session_id = store.session_key
        self.cart.save(update_fields=['session_id'])

        address = Address.objects.create(
            address_type=Address.AddressType.SHIPPING_ADDRESS,
            street_address='1 Test Street',
            city='London',
            postcode='SW12 9HR',
            session_key=store.session_key,
        )

        request = APIRequestFactory().post('/api/checkout/details/')
        request.session = store
        request.user = AnonymousUser()

        session = CheckoutSession.objects.create(cart=self.cart, email='g@example.com')
        serializer = CheckoutDetailsSerializer(
            session,
            data={'shipping_address_id': address.id, 'shipping_option_id': option.id},
            context={'request': request},
        )
        return serializer.is_valid(), serializer.errors

    def test_pickup_is_refused_when_the_cart_holds_a_fixed_dispatch_item(self):
        CartItem.objects.create(cart=self.cart, product=self.calendar, quantity=1)

        valid, errors = self.accepts(self.pickup)

        self.assertFalse(valid)
        self.assertIn('shipping_option_id', errors)
        self.assertIn('cannot be collected', str(errors['shipping_option_id']))

    def test_pickup_is_fine_for_an_ordinary_cart(self):
        CartItem.objects.create(cart=self.cart, product=self.box, quantity=1)

        valid, errors = self.accepts(self.pickup)

        self.assertTrue(valid, errors)

    def test_shipping_is_always_fine(self):
        CartItem.objects.create(cart=self.cart, product=self.calendar, quantity=1)

        valid, errors = self.accepts(self.shipping)

        self.assertTrue(valid, errors)

    def test_a_past_fixed_date_does_not_block_pickup(self):
        from datetime import timedelta
        from django.utils import timezone

        self.calendar.fixed_dispatch_date = timezone.localdate() - timedelta(days=1)
        self.calendar.save(update_fields=['fixed_dispatch_date'])
        CartItem.objects.create(cart=self.cart, product=self.calendar, quantity=1)

        valid, errors = self.accepts(self.pickup)

        self.assertTrue(valid, errors)


class StripeHostedSessionTest(TestCase):
    """What the hosted checkout actually sends to Stripe.

    Payments went down because Stripe removed `payment_method_types` from
    Checkout Session creation and started answering 400 to it. The parameter had
    been there since the beginning and nothing exercised the kwargs this view
    builds, so there was nothing to notice - prepare_stripe_payload is tested,
    but this view does not use it. These drive the view itself with Stripe
    mocked, and assert on the call.
    """

    def setUp(self):
        from rest_framework.test import APIClient

        from addresses.models import Address

        self.client = APIClient()

        # A guest checkout, which is how most orders arrive, and the only case
        # that carries an email: CheckoutSession.save() clears email for a cart
        # with a user, so Stripe collects it on its own page for those.
        store = self.client.session
        store.save()

        self.cart = Cart.objects.create(session_id=store.session_key)
        self.box = make_product('Box of 9', '14.99')
        CartItem.objects.create(cart=self.cart, product=self.box, quantity=2)

        address = Address.objects.create(
            address_type=Address.AddressType.SHIPPING_ADDRESS,
            street_address='1 Test Street',
            city='London',
            postcode='SW12 9HR',
            session_key=store.session_key,
        )
        CheckoutSession.objects.create(
            cart=self.cart,
            email='buyer@example.com',
            shipping_address=address,
            shipping_option=make_shipping_option('5.99'),
        )

    def post(self):
        """POST the real endpoint, returning the response and the Stripe mock."""
        created = mock.Mock(
            id='cs_test_123',
            url='https://checkout.stripe.com/c/pay/cs_test_123',
            amount_total=3597,
        )
        with mock.patch(
            'checkout.stripe_views.stripe.checkout.Session.create',
            return_value=created,
        ) as create:
            response = self.client.post('/api/checkout/stripe/create-session/')
        return response, create

    def test_it_returns_the_stripe_url(self):
        response, create = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(create.called)
        self.assertEqual(
            response.data['url'], 'https://checkout.stripe.com/c/pay/cs_test_123'
        )

    def test_it_does_not_send_payment_method_types(self):
        """Regression: sending it is a 400 from Stripe, i.e. nobody can pay."""
        _, create = self.post()

        self.assertNotIn('payment_method_types', create.call_args.kwargs)

    def test_it_still_sends_everything_else(self):
        """The parameter went; nothing travelling with it was meant to."""
        _, create = self.post()
        kwargs = create.call_args.kwargs

        self.assertEqual(kwargs['mode'], 'payment')
        self.assertEqual(kwargs['customer_email'], 'buyer@example.com')
        self.assertEqual(len(kwargs['line_items']), 1)
        self.assertEqual(kwargs['line_items'][0]['quantity'], 2)
        self.assertEqual(
            kwargs['shipping_options'][0]['shipping_rate_data']['fixed_amount']['amount'],
            599,
        )
