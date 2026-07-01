from datetime import timedelta

from django.utils import timezone

from carts.models import Cart
from discounts.models import Discount

from .test_base import BaseAPITest


class CartAPITest(BaseAPITest):
    def test_get_or_create_cart(self):
        """GET /api/carts/ creates a session cart and reuses it afterwards."""
        response = self.client.get('/api/carts/')

        self.assertEqual(response.status_code, 200)
        self.assertIn('id', response.data)
        self.assertIn('items', response.data)
        self.assertIn('base_total', response.data)
        self.assertIn('discounted_total', response.data)

        cart_id = response.data['id']
        self.assertTrue(Cart.objects.filter(id=cart_id).exists())

        # Same session gets the same cart back.
        response2 = self.client.get('/api/carts/')
        self.assertEqual(response2.data['id'], cart_id)

    def test_add_item_to_cart_pick_and_mix(self):
        """POST /api/carts/items/ with explicit flavour selections."""
        data = {
            "product": 4,  # 9-piece box, £14.99
            "quantity": 2,
            "box_customization": {
                "selection_type": "PICK_AND_MIX",
                "allergens": [1],
                "flavor_selections": [{"flavor": 1, "quantity": 9}],
            },
        }

        response = self.client.post('/api/carts/items/', data, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data['items']), 1)
        self.assertEqual(response.data['items'][0]['product']['id'], 4)
        self.assertEqual(response.data['items'][0]['quantity'], 2)
        self.assertEqual(response.data['base_total'], '29.98')  # 14.99 * 2
        self.assertEqual(response.data['discounted_total'], '29.98')

    def test_pick_and_mix_rejects_wrong_flavour_count(self):
        """Flavour quantities must add up to the units in the box."""
        data = {
            "product": 4,  # 9-piece box
            "quantity": 1,
            "box_customization": {
                "selection_type": "PICK_AND_MIX",
                "flavor_selections": [{"flavor": 1, "quantity": 5}],
            },
        }

        response = self.client.post('/api/carts/items/', data, format='json')
        self.assertEqual(response.status_code, 400)

    def test_add_item_to_cart_random(self):
        """POST /api/carts/items/ with a random selection."""
        data = {
            "product": 4,
            "quantity": 2,
            "box_customization": {
                "selection_type": "RANDOM",
                "allergens": [1],
            },
        }

        response = self.client.post('/api/carts/items/', data, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data['items']), 1)
        self.assertEqual(response.data['base_total'], '29.98')

    def test_update_cart_details(self):
        """POST /api/carts/ updates gift message, shipping date and discount."""
        future_date = (timezone.now() + timedelta(days=7)).date().isoformat()
        data = {
            "discount_code": "NEWS10",
            "gift_message": "Happy Birthday!",
            "shipping_date": future_date,
        }

        response = self.client.post('/api/carts/', data, format='json')

        self.assertEqual(response.status_code, 200)
        cart_data = response.data['cart']
        self.assertEqual(cart_data['gift_message'], "Happy Birthday!")
        self.assertEqual(cart_data['shipping_date'], future_date)
        self.assertEqual(cart_data['discount']['code'], "NEWS10")

    def test_shipping_date_cannot_be_in_the_past(self):
        past_date = (timezone.now() - timedelta(days=1)).date().isoformat()

        response = self.client.post(
            '/api/carts/', {"shipping_date": past_date}, format='json'
        )

        self.assertEqual(response.status_code, 400)

    def test_invalid_discount_code_returns_error(self):
        response = self.client.post(
            '/api/carts/', {"discount_code": "NOT-A-CODE"}, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('discount_code', response.data)

    def test_expired_discount_code_returns_error(self):
        Discount.objects.create(
            title="Expired promo",
            code="EXPIRED10",
            stripe_id="EXPIRED10",
            discount_type=Discount.PERCENTAGE,
            amount=10,
            active=True,
            end_date=timezone.now() - timedelta(days=1),
        )

        response = self.client.post(
            '/api/carts/', {"discount_code": "EXPIRED10"}, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('discount_code', response.data)

    def test_discount_below_min_order_value_returns_error(self):
        """A code with a minimum order value can't be applied to a small cart."""
        Discount.objects.create(
            title="Big spender",
            code="BIG20",
            stripe_id="BIG20",
            discount_type=Discount.PERCENTAGE,
            amount=20,
            active=True,
            min_order_value=55,
        )

        # Cart with one 9-piece box (£14.99) is below the £55 minimum.
        self.client.post(
            '/api/carts/items/',
            {
                "product": 4,
                "quantity": 1,
                "box_customization": {"selection_type": "RANDOM"},
            },
            format='json',
        )

        response = self.client.post(
            '/api/carts/', {"discount_code": "BIG20"}, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('discount_code', response.data)

    def test_remove_discount(self):
        self.client.post('/api/carts/', {"discount_code": "NEWS10"}, format='json')

        response = self.client.post(
            '/api/carts/', {"remove_discount": True}, format='json'
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['cart']['discount'])

    def test_sold_out_product_cannot_be_added(self):
        from products.models import Product

        product = Product.objects.get(pk=4)
        product.sold_out = True
        product.save()

        response = self.client.post(
            '/api/carts/items/',
            {
                "product": 4,
                "quantity": 1,
                "box_customization": {"selection_type": "RANDOM"},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
