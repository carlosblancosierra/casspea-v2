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
