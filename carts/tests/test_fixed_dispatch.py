"""A product that leaves on one named day takes the choice away from the cart.

The advent calendars are posted as a batch so they arrive before 1 December, so
a cart holding one cannot pick its own posting date and cannot be collected.
"""
from datetime import timedelta

from django.utils import timezone

from carts.models import Cart
from products.models import Product

from .test_base import BaseAPITest


class CartFixedDispatchDateTest(BaseAPITest):
    def setUp(self):
        super().setUp()
        self.fixed = timezone.localdate() + timedelta(days=30)
        self.calendar = Product.objects.first()
        self.calendar.fixed_dispatch_date = self.fixed
        self.calendar.save(update_fields=['fixed_dispatch_date'])

    def add_to_cart(self, product):
        return self.client.post(
            '/api/carts/items/',
            {"product": product.id, "quantity": 1},
            format='json',
        )

    def test_a_cart_without_one_is_free_to_choose(self):
        """The regression that matters most: ordinary carts are untouched."""
        other = Product.objects.exclude(pk=self.calendar.pk).first()
        self.add_to_cart(other)
        chosen = (timezone.localdate() + timedelta(days=7)).isoformat()

        response = self.client.post('/api/carts/', {"shipping_date": chosen}, format='json')

        self.assertEqual(response.data['cart']['shipping_date'], chosen)

    def test_the_fixed_date_overrides_whatever_was_submitted(self):
        """The checkout hides the picker; this is what makes it a rule."""
        self.add_to_cart(self.calendar)
        chosen = (timezone.localdate() + timedelta(days=7)).isoformat()

        response = self.client.post('/api/carts/', {"shipping_date": chosen}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['cart']['shipping_date'], self.fixed.isoformat())

    def test_it_applies_even_when_no_date_was_sent(self):
        self.add_to_cart(self.calendar)

        response = self.client.post('/api/carts/', {"gift_message": "Happy Christmas"}, format='json')

        self.assertEqual(response.data['cart']['shipping_date'], self.fixed.isoformat())

    def test_a_mixed_cart_takes_the_earliest_fixed_date(self):
        """Everything goes out together, and the earliest still arrives in time."""
        earlier = Product.objects.exclude(pk=self.calendar.pk).first()
        earlier_date = timezone.localdate() + timedelta(days=10)
        earlier.fixed_dispatch_date = earlier_date
        earlier.save(update_fields=['fixed_dispatch_date'])

        self.add_to_cart(self.calendar)
        self.add_to_cart(earlier)

        response = self.client.post('/api/carts/', {"gift_message": "x"}, format='json')

        self.assertEqual(response.data['cart']['shipping_date'], earlier_date.isoformat())

    def test_a_date_that_has_passed_is_ignored(self):
        """A seasonal setting nobody cleared must not force a posting day in the
        past — that is worse than asking the customer normally."""
        self.calendar.fixed_dispatch_date = timezone.localdate() - timedelta(days=1)
        self.calendar.save(update_fields=['fixed_dispatch_date'])
        self.add_to_cart(self.calendar)
        chosen = (timezone.localdate() + timedelta(days=7)).isoformat()

        response = self.client.post('/api/carts/', {"shipping_date": chosen}, format='json')

        self.assertEqual(response.data['cart']['shipping_date'], chosen)

    def test_the_helper_reports_none_for_an_ordinary_cart(self):
        other = Product.objects.exclude(pk=self.calendar.pk).first()
        self.add_to_cart(other)

        cart = Cart.objects.get(pk=self.client.get('/api/carts/').data['id'])
        self.assertIsNone(cart.fixed_dispatch_date)
