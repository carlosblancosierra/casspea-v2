from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache

from carts.tests.test_base import BaseAPITest
from clients.models import ClientPage, ClientPageItem
from flavours.models import Flavour
from products.models import Product, ProductCategory

User = get_user_model()
CODE = 'PAPAYA-2026'


def make_client_product(slug='client-choc', step=10):
    category = ProductCategory.objects.first()
    return Product.objects.create(
        name='Client chocolate', description='x', category=category,
        base_price=Decimal('1.80'), stripe_price_id='price_test', slug=slug,
        weight=12, units_per_box=1, main_color='#000', secondary_color='#fff',
        seo_title='x', seo_description='x', client_only=True, quantity_step=step,
    )


def make_page(slug='acme', code=CODE, **extra):
    page = ClientPage(name='Acme', slug=slug, **extra)
    if code:
        page.set_access_code(code)
    page.save()
    return page


class ClientTestBase(BaseAPITest):
    def setUp(self):
        super().setUp()
        cache.clear()  # reset the unlock throttle between tests

    def unlock(self, slug='acme', code=CODE):
        return self.client.post(f'/api/clients/{slug}/unlock/', {'code': code}, format='json')


class AccessCodeTest(ClientTestBase):
    def test_code_is_hashed_and_forgiving_about_case_and_spaces(self):
        page = make_page()
        self.assertNotIn(CODE, page.access_code_hash)
        self.assertTrue(page.check_access_code('  papaya-2026 '))
        self.assertFalse(page.check_access_code('PAPAYA-2025'))
        self.assertFalse(page.check_access_code(''))

    def test_page_without_code_never_unlocks(self):
        page = make_page(code=None)
        self.assertFalse(page.check_access_code(''))
        self.assertEqual(self.unlock(code='').status_code, 400)


class ClientOnlyProductsHiddenTest(ClientTestBase):
    def setUp(self):
        super().setUp()
        self.product = make_client_product()

    def test_not_in_product_list_or_detail(self):
        ids = [p['id'] for p in self.client.get('/api/products/').data]
        self.assertNotIn(self.product.id, ids)
        self.assertEqual(self.client.get(f'/api/products/{self.product.slug}/').status_code, 404)

    def test_not_in_category_products(self):
        response = self.client.get(f'/api/products/categories/{self.product.category.slug}/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.product.id, [p['id'] for p in response.data['products']])


class ClientPageAPITest(ClientTestBase):
    def setUp(self):
        super().setUp()
        self.product = make_client_product()
        self.page = make_page(welcome_message='Hello')
        ClientPageItem.objects.create(page=self.page, product=self.product, flavour=Flavour.objects.first())

    def test_locked_page_shows_only_branding(self):
        response = self.client.get('/api/clients/acme/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['locked'])
        self.assertEqual(response.data['name'], 'Acme')
        self.assertNotIn('items', response.data)
        self.assertNotIn('welcome_message', response.data)

    def test_no_login_needed_right_code_unlocks_for_the_session(self):
        response = self.unlock(code='papaya-2026')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['locked'])
        self.assertEqual(response.data['items'][0]['product']['id'], self.product.id)
        self.assertEqual(response.data['items'][0]['product']['quantity_step'], 10)
        self.assertIsNotNone(response.data['items'][0]['flavour'])

        # Later requests in the same session see the full page.
        response = self.client.get('/api/clients/acme/')
        self.assertFalse(response.data['locked'])
        self.assertEqual(response.data['welcome_message'], 'Hello')

    def test_wrong_code_is_refused(self):
        response = self.unlock(code='nope')
        self.assertEqual(response.status_code, 400)
        self.assertTrue(self.client.get('/api/clients/acme/').data['locked'])

    def test_changing_the_code_locks_old_sessions_out(self):
        self.unlock()
        self.page.set_access_code('NEW-CODE')
        self.page.save()
        self.assertTrue(self.client.get('/api/clients/acme/').data['locked'])

    def test_unlock_is_per_page(self):
        make_page(slug='other', code='OTHER')
        self.unlock()
        self.assertTrue(self.client.get('/api/clients/other/').data['locked'])

    def test_staff_see_it_unlocked(self):
        staff = User.objects.create_user(email='s@casspea.co.uk', password='pw-12345!', is_staff=True)
        self.client.force_login(staff)
        self.assertFalse(self.client.get('/api/clients/acme/').data['locked'])

    def test_inactive_or_unknown_page_is_404(self):
        self.page.active = False
        self.page.save()
        self.assertEqual(self.client.get('/api/clients/acme/').status_code, 404)
        self.assertEqual(self.unlock().status_code, 404)
        self.assertEqual(self.client.get('/api/clients/nope/').status_code, 404)

    def test_guessing_is_throttled(self):
        statuses = [self.unlock(code=f'guess-{i}').status_code for i in range(12)]
        self.assertIn(429, statuses)


class ClientOnlyCartTest(ClientTestBase):
    def setUp(self):
        super().setUp()
        self.product = make_client_product()
        self.page = make_page()
        ClientPageItem.objects.create(page=self.page, product=self.product)

    def add(self, quantity, product=None):
        return self.client.post(
            '/api/carts/items/',
            {'product': (product or self.product).id, 'quantity': quantity},
            format='json',
        )

    def test_cannot_add_without_the_code(self):
        response = self.add(10)
        self.assertEqual(response.status_code, 400)
        self.assertIn('product', response.data)

    def test_adds_in_tens_after_unlocking_without_login(self):
        self.unlock()
        response = self.add(20)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['items'][0]['quantity'], 20)
        self.assertEqual(response.data['base_total'], '36.00')

    def test_quantity_must_be_multiple_of_step(self):
        self.unlock()
        response = self.add(13)
        self.assertEqual(response.status_code, 400)
        self.assertIn('quantity', response.data)

    def test_change_quantity_keeps_the_step(self):
        self.unlock()
        item_id = self.add(10).data['items'][0]['id']
        url = f'/api/carts/items/{item_id}/change-quantity/'
        self.assertEqual(self.client.patch(url, {'quantity': 15}, format='json').status_code, 400)
        response = self.client.patch(url, {'quantity': 30}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['items'][0]['quantity'], 30)

    def test_inactive_page_blocks_purchase(self):
        self.unlock()
        ClientPage.objects.update(active=False)
        self.assertEqual(self.add(10).status_code, 400)

    def test_normal_products_unaffected(self):
        self.assertEqual(self.add(3, product=Product.objects.get(pk=4)).status_code, 201)
