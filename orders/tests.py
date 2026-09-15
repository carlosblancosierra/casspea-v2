"""Tests for the admin order endpoints.

The detail endpoint reuses OrderListSerializer, whose past_orders field
reads state that only the list view prepares. That made every
GET /api/orders/<order_id>/ request fail, and there was no test to catch
it, so these cover both views against the same serializer.
"""
from decimal import Decimal

import unittest

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from carts.models import Cart, CartItem
from carts.tests.test_totals import make_product
from checkout.models import CheckoutSession

from .models import Order


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

    @unittest.skipUnless(
        connection.vendor == 'postgresql',
        "OrderListView aggregates past orders with ArrayAgg, which only "
        "exists on Postgres; the test settings use SQLite so this path "
        "cannot be exercised in CI.",
    )
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
