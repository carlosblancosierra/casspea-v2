from django.test import TestCase
from rest_framework.test import APIClient

class BaseAPITest(TestCase):
    fixtures = [
        'initial_discounts.json',
        'initial_products.json',
        'initial_product_category.json',
        'initial_allergens.json'
    ]

    def setUp(self):
        self.client = APIClient()

class ProductAPITest(BaseAPITest):
    def test_list_products(self):
        """Test GET /api/products/ endpoint"""
        response = self.client.get('/api/products/')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(isinstance(response.data, list))
        self.assertEqual(len(response.data), 4)  # 3 products from fixtures

        # Verify first product (48-piece box)
        product = next(p for p in response.data if p['id'] == 1)
        self.assertEqual(product['name'], "Signature Box of 48 Hand Made Chocolates")
        self.assertEqual(product['slug'], "48-bonbons")
        self.assertEqual(product['base_price'], "74.99")
        self.assertEqual(product['units_per_box'], 48)

    def test_get_product_by_slug(self):
        """Test GET /api/products/{slug}/ endpoint"""
        response = self.client.get('/api/products/48-bonbons/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], 1)
        self.assertEqual(response.data['name'], "Signature Box of 48 Hand Made Chocolates")
        self.assertEqual(response.data['base_price'], "74.99")
        self.assertEqual(response.data['category']['name'], "Signature Boxes")

    def test_get_product_invalid_slug(self):
        """Test GET /api/products/{slug}/ with invalid slug"""
        response = self.client.get('/api/products/invalid-slug/')
        self.assertEqual(response.status_code, 404)


class ProductBadgeTests(BaseAPITest):
    """The merchandising badge and the featured card's extra image."""

    def test_badge_fields_default_to_off(self):
        """A product nobody has touched carries no badge and is not featured."""
        response = self.client.get('/api/products/48-bonbons/')

        self.assertEqual(response.data['badge_text'], '')
        self.assertFalse(response.data['badge_active'])
        self.assertFalse(response.data['featured'])

    def test_badge_is_served_when_switched_on(self):
        from .models import Product

        product = Product.objects.get(slug='48-bonbons')
        product.badge_text = 'Best seller'
        product.badge_color = Product.BADGE_GREEN
        product.badge_active = True
        product.featured = True
        product.save()

        response = self.client.get('/api/products/48-bonbons/')

        self.assertEqual(response.data['badge_text'], 'Best seller')
        self.assertEqual(response.data['badge_color'], 'green')
        self.assertTrue(response.data['badge_active'])
        self.assertTrue(response.data['featured'])

    def test_badge_text_survives_being_switched_off(self):
        """badge_active is a switch, not a delete — the wording stays."""
        from .models import Product

        product = Product.objects.get(slug='48-bonbons')
        product.badge_text = 'Top pick'
        product.badge_active = True
        product.save()

        product.badge_active = False
        product.save()

        response = self.client.get('/api/products/48-bonbons/')
        self.assertEqual(response.data['badge_text'], 'Top pick')
        self.assertFalse(response.data['badge_active'])

    def test_badge_colour_is_limited_to_the_readable_presets(self):
        """A free colour is how you end up with white text on yellow."""
        from django.core.exceptions import ValidationError
        from .models import Product

        product = Product.objects.get(slug='48-bonbons')
        product.badge_color = 'yellow'

        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_category_image_is_reachable_from_a_product(self):
        """The indulgence step falls back to the category image, so a product
        payload has to carry it — the shallow serializer used not to."""
        response = self.client.get('/api/products/48-bonbons/')

        self.assertIn('image', response.data['category'])
        self.assertIn('image_webp', response.data['category'])

    def test_indulgence_and_wide_images_are_served(self):
        response = self.client.get('/api/products/48-bonbons/')

        self.assertIsNone(response.data['indulgence_image'])
        self.assertIsNone(response.data['wide_image'])
