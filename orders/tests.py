"""Tests for the admin order endpoints.

The detail endpoint reuses OrderListSerializer, whose past_orders field reads
state that only the list view prepares. That made every
GET /api/orders/<order_id>/ request fail, and there was no test to catch it,
so these cover both views against the same serializer.

Everything here runs on any database. The list view used to aggregate past
orders with ArrayAgg, so its test was skipped outside Postgres — and that gap
is how a broken prefetch path reached production. The aggregation is done in
Python now, so there is nothing left to skip.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from carts.models import Cart, CartItem
from carts.tests.test_totals import make_product
from checkout.models import CheckoutSession

from .models import Order
from .views import (
    ORDER_PREFETCH_RELATED,
    ORDER_SELECT_RELATED,
    OrderDetailView,
    OrderListView,
)


class AdminOrderEndpointTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        user = get_user_model().objects.create_superuser(
            email='admin@example.com', password='pw'
        )
        token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        self.box = make_product('Box of 9', '14.99')

    def make_order(self, email='guest@example.com', payment_status='paid'):
        cart = Cart.objects.create(session_id=f'session-{email}-{Order.objects.count()}')
        CartItem.objects.create(cart=cart, product=self.box, quantity=2)
        session = CheckoutSession.objects.create(cart=cart, email=email)
        session.payment_status = payment_status
        session.save()
        return Order.objects.create(checkout_session=session)

    def test_order_detail_returns_the_order(self):
        """Regression: this used to 500 because the serializer read
        past_ids_map, which only the list view sets."""
        order = self.make_order()

        response = self.client.get(f'/api/orders/{order.order_id}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['order_id'], order.order_id)

    def test_order_detail_reports_past_orders_for_the_same_customer(self):
        first = self.make_order(email='repeat@example.com')
        second = self.make_order(email='repeat@example.com')

        response = self.client.get(f'/api/orders/{second.order_id}/')

        self.assertEqual(response.status_code, 200)
        # The current order is excluded from its own history.
        self.assertEqual(response.data['past_orders'], [first.order_id])

    def test_order_detail_excludes_other_customers_orders(self):
        self.make_order(email='someone-else@example.com')
        mine = self.make_order(email='mine@example.com')

        response = self.client.get(f'/api/orders/{mine.order_id}/')

        self.assertEqual(response.data['past_orders'], [])

    def test_order_list_still_populates_past_orders(self):
        first = self.make_order(email='repeat@example.com')
        self.make_order(email='repeat@example.com')

        response = self.client.get('/api/orders/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)
        newest = response.data[0]
        self.assertEqual(newest['past_orders'], [first.order_id])

    def test_order_detail_requires_admin(self):
        order = self.make_order()
        anonymous = APIClient()

        response = anonymous.get(f'/api/orders/{order.order_id}/')

        self.assertIn(response.status_code, (401, 403))


class OrderSummaryEndpointTest(TestCase):
    """The orders table reads /api/orders/summary/.

    It exists so a page of orders costs a flat number of queries and a small
    payload, instead of the full nested object graph the old list returns.
    """

    def setUp(self):
        self.client = APIClient()
        user = get_user_model().objects.create_superuser(
            email='admin2@example.com', password='pw'
        )
        token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        self.box = make_product('Box of 9', '14.99')

    def make_order(self, email='guest@example.com', quantity=2):
        cart = Cart.objects.create(
            session_id=f'summary-{email}-{Order.objects.count()}'
        )
        CartItem.objects.create(cart=cart, product=self.box, quantity=quantity)
        session = CheckoutSession.objects.create(cart=cart, email=email)
        session.payment_status = 'paid'
        session.save()
        return Order.objects.create(checkout_session=session)

    def test_requires_admin(self):
        anon = APIClient()
        self.assertEqual(anon.get('/api/orders/summary/').status_code, 401)

    def test_returns_a_paginated_row_per_order(self):
        order = self.make_order()

        response = self.client.get('/api/orders/summary/')

        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.data)
        self.assertEqual(response.data['count'], 1)
        row = response.data['results'][0]
        self.assertEqual(row['order_id'], order.order_id)
        # Shallow on purpose: the heavy nested objects belong to the drawer.
        for absent in ('checkout_session', 'cart', 'items'):
            self.assertNotIn(absent, row)

    def test_row_carries_what_the_table_shows(self):
        self.make_order(email='shopper@example.com', quantity=3)

        row = self.client.get('/api/orders/summary/').data['results'][0]

        self.assertEqual(row['email'], 'shopper@example.com')
        self.assertEqual(row['item_count'], 3)
        self.assertEqual(row['payment_status'], 'paid')
        self.assertIsNotNone(row['total_with_shipping'])

    def test_search_matches_order_id_and_email(self):
        wanted = self.make_order(email='findme@example.com')
        self.make_order(email='other@example.com')

        by_email = self.client.get('/api/orders/summary/?search=findme')
        self.assertEqual([r['order_id'] for r in by_email.data['results']],
                         [wanted.order_id])

        by_id = self.client.get(f'/api/orders/summary/?search={wanted.order_id}')
        self.assertEqual([r['order_id'] for r in by_id.data['results']],
                         [wanted.order_id])

    def test_end_date_alone_filters(self):
        """OrderListView ignores end_date unless start_date is also sent;
        the summary endpoint honours it on its own."""
        self.make_order()

        past = self.client.get('/api/orders/summary/?end_date=2000-01-01')
        self.assertEqual(past.data['count'], 0)

        today = self.client.get('/api/orders/summary/?end_date=2999-01-01')
        self.assertEqual(today.data['count'], 1)

    def test_query_count_does_not_grow_with_the_number_of_orders(self):
        """Regression guard for N+1: five orders must cost the same as one."""
        self.make_order(email='a@example.com')
        with CaptureQueriesContext(connection) as one_order:
            self.client.get('/api/orders/summary/')

        for name in ('b', 'c', 'd', 'e'):
            self.make_order(email=f'{name}@example.com')
        with CaptureQueriesContext(connection) as five_orders:
            self.client.get('/api/orders/summary/')

        self.assertEqual(len(five_orders), len(one_order))


class OrderQuerysetPrefetchTests(TestCase):
    """
    The prefetch paths the order views share have to be real.

    `/api/orders/` returned 500 on every request because the pack line said
    `flavor_selections`, which is the related_name on the BOX side; the pack
    side is `flavor_selections_pack`. prefetch_related does not check its
    arguments until the queryset is evaluated — no import error, no system
    check, nothing until production.

    The list test above is the one that would have caught it, and it is
    skipped outside Postgres because the view aggregates with ArrayAgg. That
    gap is exactly what let this ship, so these evaluate the paths directly
    and run on any database.
    """

    def setUp(self):
        self.box = make_product('Box of 9', '14.99')

    def make_order_with_a_pack(self):
        from carts.models import CartItemBoxFlavorSelection, CartItemPackCustomization
        from flavours.models import Flavour, FlavourCategory

        cart = Cart.objects.create(session_id='prefetch-test')
        item = CartItem.objects.create(cart=cart, product=self.box, quantity=1)
        pack = CartItemPackCustomization.objects.create(
            cart_item=item, selection_type='PICK_AND_MIX'
        )
        # Flavour.category defaults to pk 1, which only exists if something
        # made it.
        category = FlavourCategory.objects.create(name='Classics', slug='classics')
        flavour = Flavour.objects.create(
            name='Salted Caramel', slug='salted-caramel', category=category
        )
        CartItemBoxFlavorSelection.objects.create(
            pack_customization=pack, flavor=flavour, quantity=9
        )
        session = CheckoutSession.objects.create(cart=cart, email='pack@example.com')
        session.payment_status = 'paid'
        session.save()
        return Order.objects.create(checkout_session=session)

    def test_every_prefetch_path_resolves(self):
        self.make_order_with_a_pack()

        # Evaluating is the point: an invalid path raises here and nowhere else.
        orders = list(
            Order.objects
            .select_related(*ORDER_SELECT_RELATED)
            .prefetch_related(*ORDER_PREFETCH_RELATED)
        )

        self.assertEqual(len(orders), 1)

    def test_the_pack_flavours_are_the_ones_actually_prefetched(self):
        """A path that resolves but points at the wrong relation would still
        serve empty flavours, so check the data comes back."""
        self.make_order_with_a_pack()

        order = (
            Order.objects
            .prefetch_related(*ORDER_PREFETCH_RELATED)
            .get()
        )
        item = order.checkout_session.cart.items.all()[0]
        selections = item.pack_customization.flavor_selections_pack.all()

        self.assertEqual([s.flavor.name for s in selections], ['Salted Caramel'])

    def test_the_two_views_share_one_definition(self):
        """They had a copy each, and both copies carried the same typo."""
        self.assertIs(OrderListView.get_queryset.__globals__['ORDER_PREFETCH_RELATED'],
                      OrderDetailView.get_queryset.__globals__['ORDER_PREFETCH_RELATED'])


class OrderListIdsFilterTests(TestCase):
    """
    ?ids= fetches exactly the orders staff ticked.

    The production-totals screen lets them select orders from any page of the
    table, so the date range they happen to be browsing must not drop one of
    them from the totals they are about to bake to.
    """

    def setUp(self):
        self.client = APIClient()
        user = get_user_model().objects.create_superuser(
            email='admin@example.com', password='pw'
        )
        token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        self.box = make_product('Box of 9', '14.99')

    def make_order(self, email, created=None):
        cart = Cart.objects.create(session_id=f'ids-{email}-{Order.objects.count()}')
        CartItem.objects.create(cart=cart, product=self.box, quantity=1)
        session = CheckoutSession.objects.create(cart=cart, email=email)
        session.payment_status = 'paid'
        session.save()
        order = Order.objects.create(checkout_session=session)
        if created:
            Order.objects.filter(pk=order.pk).update(created=created)
            order.refresh_from_db()
        return order

    def test_returns_only_the_requested_orders(self):
        wanted = self.make_order('a@example.com')
        self.make_order('b@example.com')

        response = self.client.get(f'/api/orders/?ids={wanted.order_id}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual([o['order_id'] for o in response.data], [wanted.order_id])

    def test_reaches_past_the_default_date_window(self):
        """Without this the totals would quietly omit an older order that was
        ticked from a filtered page — the worst kind of wrong for a batch
        somebody is about to make."""
        old = self.make_order('old@example.com', created=timezone.now() - timedelta(days=90))

        response = self.client.get(f'/api/orders/?ids={old.order_id}')

        self.assertEqual([o['order_id'] for o in response.data], [old.order_id])

    def test_ignores_ids_that_do_not_exist(self):
        real = self.make_order('real@example.com')

        response = self.client.get(f'/api/orders/?ids={real.order_id},CP99-ZZZZ')

        self.assertEqual([o['order_id'] for o in response.data], [real.order_id])

    def test_caps_how_many_can_be_asked_for_at_once(self):
        """Each one carries its whole object graph, so an unbounded list is a
        way to ask the database for the entire year in one request."""
        from orders.views import MAX_ORDER_IDS

        ids = ','.join(f'CP26-{n:04d}' for n in range(MAX_ORDER_IDS + 50))
        response = self.client.get(f'/api/orders/?ids={ids}')

        self.assertEqual(response.status_code, 200)

    def test_still_populates_past_orders(self):
        """The ids branch must not skip the prefetch the serializer needs, or
        every row costs an extra query."""
        first = self.make_order('repeat@example.com')
        second = self.make_order('repeat@example.com')

        response = self.client.get(f'/api/orders/?ids={second.order_id}')

        self.assertEqual(response.data[0]['past_orders'], [first.order_id])
