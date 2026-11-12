from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models.fields.files import FieldFile

from carts.tests.test_base import BaseAPITest
from clients.models import ClientPage, ClientPageItem
from products.models import Product

User = get_user_model()
URL = '/api/clients/admin/setups/'


class ClientSetupAdminTest(BaseAPITest):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.superuser = User.objects.create_user(
            email='boss@casspea.co.uk', password='pw-12345!', is_staff=True, is_superuser=True,
        )
        self.staff = User.objects.create_user(
            email='staff@casspea.co.uk', password='pw-12345!', is_staff=True,
        )

    def load(self, **extra):
        return self.client.post(URL, {'setup': 'wild-at-heart', **extra}, format='json')

    def test_only_super_admins(self):
        self.assertIn(self.client.get(URL).status_code, (401, 403))
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.assertEqual(self.load().status_code, 403)
        self.assertFalse(ClientPage.objects.exists())

    def test_status_lists_setups(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        setup = response.data['setups'][0]
        self.assertEqual(setup['key'], 'wild-at-heart')
        self.assertFalse(setup['page_exists'])
        self.assertEqual(len(setup['products']), 3)

    def test_load_creates_page_code_and_hidden_boxes(self):
        self.client.force_authenticate(self.superuser)
        response = self.load()
        self.assertEqual(response.status_code, 200)
        code = response.data['access_code']
        self.assertTrue(code.startswith('WAH-'))

        page = ClientPage.objects.get(slug='wild-at-heart')
        self.assertTrue(page.check_access_code(code))
        self.assertEqual(page.items.count(), 3)

        box9 = Product.objects.get(slug='wild-at-heart-box-9')
        source = Product.objects.get(slug='9-bonbons')
        self.assertEqual(box9.base_price, Decimal('13.00'))
        self.assertEqual(box9.stripe_price_id, 'price_1UaJ4LJiuFqKKcn6xRPbMmta')
        self.assertEqual(box9.units_per_box, 9)
        self.assertEqual(box9.weight, source.weight)
        self.assertTrue(box9.client_only)
        self.assertTrue(box9.disable_flavour_selection)
        self.assertEqual(box9.quantity_step, 1)
        self.assertFalse(box9.category.active)
        self.assertFalse(Product.objects.active().filter(client_only=True).exists())
        self.assertTrue(all(p['up_to_date'] for p in response.data['status']['products']))

    def test_reload_keeps_code_and_does_not_duplicate(self):
        self.client.force_authenticate(self.superuser)
        code = self.load().data['access_code']
        response = self.load()
        self.assertIsNone(response.data['access_code'])
        self.assertTrue(ClientPage.objects.get(slug='wild-at-heart').check_access_code(code))
        self.assertEqual(Product.objects.filter(client_only=True).count(), 3)
        self.assertEqual(ClientPageItem.objects.count(), 3)

    def test_new_code_replaces_it(self):
        self.client.force_authenticate(self.superuser)
        old = self.load().data['access_code']
        new = self.load(new_code=True).data['access_code']
        self.assertNotEqual(old, new)
        page = ClientPage.objects.get(slug='wild-at-heart')
        self.assertFalse(page.check_access_code(old))
        self.assertTrue(page.check_access_code(new))

    def test_dry_run_saves_nothing(self):
        self.client.force_authenticate(self.superuser)
        response = self.load(dry_run=True)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['access_code'])
        self.assertFalse(ClientPage.objects.exists())
        self.assertFalse(Product.objects.filter(client_only=True).exists())

    def test_unknown_setup(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.post(URL, {'setup': 'nope'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_loaded_page_works_end_to_end(self):
        self.client.force_authenticate(self.superuser)
        code = self.load().data['access_code']
        self.client.force_authenticate(None)
        self.client.logout()
        unlocked = self.client.post('/api/clients/wild-at-heart/unlock/', {'code': code}, format='json')
        self.assertEqual(unlocked.status_code, 200)
        box15 = Product.objects.get(slug='wild-at-heart-box-15')
        response = self.client.post('/api/carts/items/', {
            'product': box15.id, 'quantity': 2,
            'box_customization': {'selection_type': 'RANDOM', 'allergens': [], 'flavor_selections': []},
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['base_total'], '42.00')


class SharedImageDeleteTest(BaseAPITest):
    def test_deleting_a_product_keeps_images_another_product_uses(self):
        source = Product.objects.get(slug='9-bonbons')
        clone = Product.objects.get(pk=source.pk)
        clone.pk = None
        clone.slug = 'clone-9'
        clone.save()
        # Set the shared file without save(), which would try to process it.
        Product.objects.filter(pk__in=[source.pk, clone.pk]).update(image='flavours/box9.jpg')

        deleted = []
        with mock.patch.object(FieldFile, 'delete', lambda self, save=True: deleted.append(self.name)):
            Product.objects.get(pk=clone.pk).delete()
        self.assertEqual(deleted, [])
        self.assertTrue(Product.objects.filter(pk=source.pk).exists())

    def test_deleting_a_product_removes_images_nobody_else_uses(self):
        product = Product.objects.get(slug='9-bonbons')
        Product.objects.filter(pk=product.pk).update(image='flavours/only-mine.jpg')
        deleted = []
        with mock.patch.object(FieldFile, 'delete', lambda self, save=True: deleted.append(self.name)):
            Product.objects.get(pk=product.pk).delete()
        self.assertEqual(deleted, ['flavours/only-mine.jpg'])
