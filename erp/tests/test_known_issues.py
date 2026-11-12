"""Known defects, each pinned by a test that describes the correct behaviour.

Every test here is marked @expectedFailure: it fails today, so the suite stays
green while the bug exists. Fixing the bug makes the test pass, Django reports
an "unexpected success" and the run goes red. That is the signal to delete
the decorator, keep the test as a regression guard, and tick the bug off in
next-casspea/docs/plan-rediseno-seguro.md, where the IDs come from.
"""
import re
from pathlib import Path
from unittest import expectedFailure, mock

import stripe
from django.conf import settings
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from carts.models import Cart, CartItem
from carts.tests.test_totals import make_product
from checkout.models import CheckoutSession
from checkout.stripe_utils import prepare_stripe_payload
from checkout.tests import make_shipping_option

WEBHOOK_URL = '/api/checkout/stripe/webhook/'


def stripe_event(event_type, obj):
    """A real StripeObject, as stripe.Webhook.construct_event returns it."""
    return stripe.Event.construct_from(
        {'id': 'evt_test', 'type': event_type, 'data': {'object': obj}}, 'sk_test_dummy'
    )


def post_webhook(client, event, **extra):
    with mock.patch('checkout.webhooks.stripe.Webhook.construct_event', return_value=event), \
            mock.patch('checkout.webhooks.stripe.checkout.Session.list_line_items',
                       side_effect=stripe.error.APIConnectionError('offline in tests')):
        return client.post(WEBHOOK_URL, data=b'{}', content_type='application/json',
                           HTTP_STRIPE_SIGNATURE='t=1,v1=sig', **extra)


class GuestCheckoutMixin:
    def start_guest_checkout(self, client, email):
        product = make_product(f'Box {email}', '14.99')
        client.get('/api/carts/')
        client.post('/api/carts/items/', {'product': product.id, 'quantity': 1}, format='json')
        client.post('/api/checkout/session/', {'email': email}, format='json')
        client.post('/api/addresses/', {'shipping_address': {
            'address_type': 'SHIPPING', 'full_name': 'Ada Lovelace', 'phone': '07700900123',
            'street_address': '1 Private Road', 'city': 'London', 'postcode': 'SW1A 1AA',
        }}, format='json')
        return CheckoutSession.objects.get(email=email)


class Bug01DependencyConfusionTest(TestCase):
    """BUG-01: requirements.txt installs `rest_framework_simplejwt`, a
    dependency-confusion proof-of-concept package (0.0.2), into production.
    The real library is `djangorestframework-simplejwt`, already listed."""

    @expectedFailure
    def test_requirements_do_not_install_the_poc_package(self):
        lines = (Path(settings.BASE_DIR) / 'requirements.txt').read_text().splitlines()
        names = {re.split(r'[<>=!~\[ ;]', line.strip(), maxsplit=1)[0].lower()
                 for line in lines if line.strip() and not line.startswith('#')}
        self.assertNotIn('rest_framework_simplejwt', names)


class Bug02CheckoutSessionPrivacyTest(GuestCheckoutMixin, TestCase):
    """BUG-02: checkout sessions are readable and writable by id by anyone.
    The ids are sequential, so every customer's email, phone and address can
    be enumerated."""

    def setUp(self):
        self.victim = APIClient()
        self.session = self.start_guest_checkout(self.victim, 'victim@example.com')
        self.stranger = APIClient()

    def test_the_owner_can_read_their_own_session(self):
        response = self.victim.get(f'/api/checkout/session/{self.session.id}/')
        self.assertEqual(response.status_code, 200)

    @expectedFailure
    def test_a_stranger_cannot_read_someone_elses_session(self):
        response = self.stranger.get(f'/api/checkout/session/{self.session.id}/')
        self.assertIn(response.status_code, (403, 404))
        self.assertNotIn(b'victim@example.com', response.content)

    @expectedFailure
    def test_a_stranger_cannot_change_someone_elses_shipping_option(self):
        option = make_shipping_option()
        response = self.stranger.post(
            f'/api/checkout/session/{self.session.id}/shipping-option/',
            {'shipping_option_id': option.id}, format='json')
        self.assertIn(response.status_code, (403, 404))


class Bug03UnpaidCompletionTest(TestCase):
    """BUG-03: checkout.session.completed is handled as a payment even when
    Stripe says payment_status is 'unpaid' (delayed methods such as bank
    debits or vouchers finish later, or never)."""

    def setUp(self):
        cart = Cart.objects.create(session_id='bug-03')
        CartItem.objects.create(cart=cart, product=make_product('Box of 9', '14.99'), quantity=1)
        self.session = CheckoutSession.objects.create(cart=cart, email='guest@example.com')

    @expectedFailure
    def test_unpaid_completion_does_not_mark_the_session_paid(self):
        event = stripe_event('checkout.session.completed', {
            'id': 'cs_test', 'object': 'checkout.session', 'payment_status': 'unpaid',
            'payment_intent': 'pi_test', 'metadata': {'checkout_session_id': str(self.session.id)},
        })
        post_webhook(self.client, event)
        self.session.refresh_from_db()
        self.assertNotEqual(self.session.payment_status, CheckoutSession.Status.PAID)


class Bug07PaymentFailedTest(TestCase):
    """BUG-07 (fixed): payment_intent.payment_failed read checkout_session_id
    from the PaymentIntent's metadata, but only the Checkout Session carried
    it. Every such event answered 500, so Stripe kept retrying it."""

    def setUp(self):
        cart = Cart.objects.create(session_id='bug-07')
        CartItem.objects.create(cart=cart, product=make_product('Box of 9', '14.99'), quantity=1)
        self.session = CheckoutSession.objects.create(
            cart=cart, email='guest@example.com', shipping_option=make_shipping_option())

    def failed(self, metadata):
        return stripe_event('payment_intent.payment_failed', {
            'id': 'pi_test', 'object': 'payment_intent', 'metadata': metadata,
        })

    def test_payment_failed_without_session_metadata_is_acknowledged(self):
        self.assertEqual(post_webhook(self.client, self.failed({})).status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.payment_status, CheckoutSession.Status.PENDING)

    def test_payment_failed_with_session_metadata_marks_it_failed(self):
        response = post_webhook(self.client, self.failed({'checkout_session_id': str(self.session.id)}))
        self.assertEqual(response.status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.payment_status, CheckoutSession.Status.FAILED)

    def test_a_late_failure_never_undoes_a_paid_session(self):
        self.session.payment_status = CheckoutSession.Status.PAID
        self.session.save()
        post_webhook(self.client, self.failed({'checkout_session_id': str(self.session.id)}))
        self.session.refresh_from_db()
        self.assertEqual(self.session.payment_status, CheckoutSession.Status.PAID)

    def test_both_checkouts_copy_the_session_id_onto_the_payment_intent(self):
        expected = {'metadata': {'checkout_session_id': str(self.session.id)}}
        self.assertEqual(prepare_stripe_payload(self.session, embedded=True)['payment_intent_data'], expected)

        from addresses.models import Address
        self.session.shipping_address = Address.objects.create(
            street_address='1 Test Street', city='London', postcode='SW1A 1AA')
        self.session.save()
        client = APIClient()
        with mock.patch('checkout.stripe_views.CheckoutSession.objects.get_or_create_from_request',
                        return_value=self.session), \
                mock.patch('checkout.stripe_views.stripe.checkout.Session.create',
                           return_value=mock.Mock(id='cs_test', url='https://checkout.stripe.com/x')) as create:
            response = client.post('/api/checkout/stripe/create-session/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(create.call_args.kwargs['payment_intent_data'], expected)


class Bug10GuestSessionTest(TestCase):
    """BUG-10: GET /api/checkout/session/ answers 500 to every guest who has
    not typed an email yet. The cart page calls it on load."""

    @expectedFailure
    def test_a_new_guest_can_fetch_their_checkout_session(self):
        client = APIClient()
        client.get('/api/carts/')
        self.assertEqual(client.get('/api/checkout/session/').status_code, 200)


class Bug11WebhookSignatureTest(TestCase):
    """BUG-11: a webhook call without a Stripe-Signature header raises KeyError
    (500) instead of being rejected with 400."""

    @expectedFailure
    def test_missing_signature_header_is_a_400(self):
        client = APIClient(raise_request_exception=False)
        response = client.post(WEBHOOK_URL, data=b'{}', content_type='application/json')
        self.assertEqual(response.status_code, 400)


class Bug12QuantityValidationTest(TestCase):
    """BUG-12: a non-numeric quantity raises ValueError (500) instead of 400."""

    @expectedFailure
    def test_non_numeric_quantity_is_a_400(self):
        client = APIClient(raise_request_exception=False)
        client.get('/api/carts/')
        product = make_product('Box of 9', '14.99')
        response = client.post('/api/carts/items/', {'product': product.id, 'quantity': 'abc'}, format='json')
        self.assertEqual(response.status_code, 400)


class Bug13FrontendUrlTest(TestCase):
    """BUG-13: Stripe's return URLs are hardcoded to www.casspea.co.uk, so a
    checkout started on a preview or staging frontend sends the customer back
    to production. They should come from one setting."""

    @expectedFailure
    @override_settings(FRONTEND_URL='https://preview.casspea.test')
    def test_stripe_return_urls_follow_the_frontend_url_setting(self):
        cart = Cart.objects.create(session_id='bug-13')
        CartItem.objects.create(cart=cart, product=make_product('Box of 9', '14.99'), quantity=1)
        session = CheckoutSession.objects.create(
            cart=cart, email='guest@example.com', shipping_option=make_shipping_option())
        payload = prepare_stripe_payload(session, embedded=True)
        self.assertTrue(payload['return_url'].startswith('https://preview.casspea.test/'))


class Bug19FixedDispatchPickupTest(GuestCheckoutMixin, TestCase):
    """BUG-19: a cart holding a fixed-dispatch product (the advent calendars,
    posted together on a named day) must not be collected in store. The rule
    lives in CheckoutDetailsSerializer, which no view uses: the endpoints the
    storefront calls, POST /api/checkout/session/ and .../shipping-option/,
    set the pickup option without asking. FixedDispatchBlocksPickupTest in
    checkout/tests.py tests the serializer directly, so it passes anyway."""

    def setUp(self):
        from datetime import timedelta
        from decimal import Decimal

        from django.utils import timezone
        from shipping.models import ShippingCompany, ShippingOption

        self.client = APIClient()
        self.session = self.start_guest_checkout(self.client, 'advent@example.com')
        calendar = make_product('Advent Calendar', '49.99')
        calendar.fixed_dispatch_date = timezone.localdate() + timedelta(days=30)
        calendar.save(update_fields=['fixed_dispatch_date'])
        self.client.post('/api/carts/items/', {'product': calendar.id, 'quantity': 1}, format='json')
        company, _ = ShippingCompany.objects.get_or_create(code='test-courier', defaults={'name': 'Test Courier'})
        self.pickup = ShippingOption.objects.create(
            company=company, name='Store pickup', delivery_speed='PICKUP',
            price=Decimal('0.00'), estimated_days_min=0, estimated_days_max=0,
        )

    @expectedFailure
    def test_store_pickup_is_refused_for_a_fixed_dispatch_cart(self):
        response = self.client.post(
            f'/api/checkout/session/{self.session.id}/shipping-option/',
            {'shipping_option_id': self.pickup.id, 'pickup_date': '2026-12-01', 'pickup_time': '10:00 - 11:00'},
            format='json')
        self.assertEqual(response.status_code, 400)
        self.session.refresh_from_db()
        self.assertNotEqual(self.session.shipping_option, self.pickup)
