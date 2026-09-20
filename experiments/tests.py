"""
Tests for the box-builder A/B experiment.

The point of this app is that the money metric survives things a client-side
analytics tag does not — a consent banner, an ad blocker, the full-page
redirect to Stripe. So the tests that matter most are the ones about the
purchase join, and about every failure path returning control rather than
breaking the shop.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from carts.models import Cart, CartItem
from carts.tests.test_totals import make_product
from checkout.models import CheckoutSession
from orders.models import Order

from .models import Assignment, Event, Experiment

BROWSER_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15'


class ExperimentTestCase(TestCase):
    def setUp(self):
        self.client = APIClient(HTTP_USER_AGENT=BROWSER_UA)
        self.experiment = Experiment.objects.create(
            key='box_builder',
            name='Box builder',
            variants={'control': 50, 'quick': 50},
        )

    def assign(self, client=None, **extra):
        return (client or self.client).post(
            '/api/experiments/assign/', {'experiment': 'box_builder'}, format='json', **extra
        )


class AssignmentTests(ExperimentTestCase):
    def test_assigns_a_variant_from_the_configured_set(self):
        response = self.assign()

        self.assertEqual(response.status_code, 200)
        self.assertIn(response.data['variant'], {'control', 'quick'})
        self.assertEqual(Assignment.objects.count(), 1)

    def test_the_same_visitor_keeps_the_same_variant(self):
        """A visitor re-bucketed on reload would appear in both arms and make
        every rate meaningless."""
        first = self.assign().data['variant']

        for _ in range(5):
            self.assertEqual(self.assign().data['variant'], first)

        self.assertEqual(Assignment.objects.count(), 1)

    def test_different_visitors_are_split_across_both_variants(self):
        for _ in range(60):
            self.assign(client=APIClient(HTTP_USER_AGENT=BROWSER_UA))

        variants = set(Assignment.objects.values_list('variant', flat=True))
        self.assertEqual(variants, {'control', 'quick'})

    def test_weights_are_honoured(self):
        self.experiment.variants = {'control': 100, 'quick': 0}
        self.experiment.save()

        for _ in range(20):
            self.assign(client=APIClient(HTTP_USER_AGENT=BROWSER_UA))

        self.assertEqual(
            set(Assignment.objects.values_list('variant', flat=True)), {'control'}
        )

    def test_switching_the_experiment_off_sends_everyone_to_control(self):
        """The kill switch has to work without a deploy."""
        self.experiment.active = False
        self.experiment.save()

        response = self.assign()

        self.assertEqual(response.data['variant'], 'control')
        self.assertEqual(Assignment.objects.count(), 0)

    def test_an_unknown_experiment_returns_control_rather_than_an_error(self):
        response = self.client.post(
            '/api/experiments/assign/', {'experiment': 'not-a-thing'}, format='json'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['variant'], 'control')

    def test_crawlers_are_not_assigned(self):
        """Bots never buy. In the denominator they drag both conversion rates
        towards zero, and they do not crawl the two arms evenly."""
        bot = APIClient(HTTP_USER_AGENT='Mozilla/5.0 (compatible; Googlebot/2.1)')

        response = bot.post('/api/experiments/assign/', {'experiment': 'box_builder'}, format='json')

        self.assertEqual(response.data['variant'], 'control')
        self.assertEqual(Assignment.objects.count(), 0)


class EventTests(ExperimentTestCase):
    def test_records_an_event_against_the_assignment(self):
        self.assign()

        response = self.client.post(
            '/api/experiments/event/',
            {'experiment': 'box_builder', 'name': Event.ADD_TO_CART},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Event.objects.count(), 1)

    def test_an_unassigned_visitor_records_nothing(self):
        response = self.client.post(
            '/api/experiments/event/',
            {'experiment': 'box_builder', 'name': Event.ADD_TO_CART},
            format='json',
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(Event.objects.count(), 0)

    def test_rejects_an_event_name_no_report_reads(self):
        self.assign()

        response = self.client.post(
            '/api/experiments/event/',
            {'experiment': 'box_builder', 'name': 'whatever_i_like'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Event.objects.count(), 0)


class ResultsTests(ExperimentTestCase):
    def setUp(self):
        super().setUp()
        self.admin_client = APIClient()
        admin = get_user_model().objects.create_superuser(email='admin@example.com', password='pw')
        token = RefreshToken.for_user(admin).access_token
        self.admin_client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        self.box = make_product('Box of 9', '14.99')

    def make_assignment(self, variant, session_id):
        return Assignment.objects.create(
            experiment=self.experiment, variant=variant, session_id=session_id
        )

    def make_paid_order(self, session_id, payment_status='paid', quantity=1):
        cart = Cart.objects.create(session_id=session_id)
        CartItem.objects.create(cart=cart, product=self.box, quantity=quantity)
        session = CheckoutSession.objects.create(cart=cart, email=f'{session_id}@example.com')
        session.payment_status = payment_status
        session.save()
        return Order.objects.create(checkout_session=session)

    def results(self):
        response = self.admin_client.get('/api/experiments/box_builder/results/')
        self.assertEqual(response.status_code, 200)
        return {row['variant']: row for row in response.data['variants']}

    def test_joins_a_paid_order_to_the_variant_that_visitor_saw(self):
        """The whole design: the purchase is a database join from the session
        the cart already uses, not an event the browser had to survive Stripe
        to send."""
        self.make_assignment('quick', 'session-quick')
        self.make_paid_order('session-quick')

        rows = self.results()

        self.assertEqual(rows['quick']['orders'], 1)
        self.assertEqual(rows['quick']['revenue'], '14.99')
        self.assertEqual(rows['control']['orders'], 0)

    def test_ignores_orders_that_were_never_paid_for(self):
        self.make_assignment('quick', 'session-quick')
        self.make_paid_order('session-quick', payment_status='pending')

        self.assertEqual(self.results()['quick']['orders'], 0)

    def test_ignores_orders_from_visitors_who_were_never_in_the_experiment(self):
        self.make_assignment('quick', 'session-quick')
        self.make_paid_order('some-other-session')

        rows = self.results()

        self.assertEqual(rows['quick']['orders'], 0)
        self.assertEqual(rows['control']['orders'], 0)

    def test_counts_add_to_cart_once_per_visitor(self):
        """Someone adding three boxes is one person who reached the cart, not
        three."""
        assignment = self.make_assignment('quick', 'session-quick')
        for _ in range(3):
            Event.objects.create(assignment=assignment, name=Event.ADD_TO_CART)

        self.assertEqual(self.results()['quick']['add_to_carts'], 1)

    def test_reports_the_rates_the_decision_turns_on(self):
        for i in range(4):
            self.make_assignment('quick', f'quick-{i}')
        assignment = Assignment.objects.get(session_id='quick-0')
        Event.objects.create(assignment=assignment, name=Event.ADD_TO_CART)
        self.make_paid_order('quick-0')

        row = self.results()['quick']

        self.assertEqual(row['visitors'], 4)
        self.assertEqual(row['add_to_cart_rate'], 0.25)
        self.assertEqual(row['order_rate'], 0.25)
        self.assertEqual(row['revenue_per_visitor'], '3.75')

    def test_results_are_admin_only(self):
        response = self.client.get('/api/experiments/box_builder/results/')

        self.assertIn(response.status_code, (401, 403))
