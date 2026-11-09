from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command

from carts.tests.test_base import BaseAPITest
from clients.models import ClientPage, ClientPageItem
from flavours.models import Flavour
from products.models import Product, ProductCategory

User = get_user_model()


def make_client_product(slug='client-choc', step=10):
    category = ProductCategory.objects.first()
    return Product.objects.create(
        name='Client chocolate', description='x', category=category,
        base_price=Decimal('1.80'), stripe_price_id='price_test', slug=slug,
        weight=12, units_per_box=1, main_color='#000', secondary_color='#fff',
        seo_title='x', seo_description='x', client_only=True, quantity_step=step,
    )


class ClientPageAccessTest(BaseAPITest):
    def setUp(self):
        super().setUp()
        self.page = ClientPage.objects.create(
            name='Acme', slug='acme', allowed_emails='anna@acme.com\n@team.acme.com',
        )

    def user(self, email, **extra):
        return User.objects.create_user(email=email, password='pw-12345!', **extra)

    def test_allows_listed_email_domain_and_staff_only(self):
        self.assertTrue(self.page.allows(self.user('Anna@Acme.com')))
        self.assertTrue(self.page.allows(self.user('bob@team.acme.com')))
        self.assertTrue(self.page.allows(self.user('boss@casspea.co.uk', is_staff=True)))
        self.assertFalse(self.page.allows(self.user('bob@acme.com')))
        self.assertFalse(self.page.allows(self.user('eve@evil-team.acme.com.fake.com')))

    def test_empty_list_means_staff_only(self):
        page = ClientPage.objects.create(name='Empty', slug='empty')
        self.assertFalse(page.allows(self.user('anna@acme.com')))
        self.assertTrue(page.allows(self.user('staff@casspea.co.uk', is_staff=True)))


class ClientOnlyProductsHiddenTest(BaseAPITest):
    def setUp(self):
        super().setUp()
        self.product = make_client_product()

    def test_not_in_product_list_or_detail(self):
        response = self.client.get('/api/products/')
        ids = [p['id'] for p in response.data]
        self.assertNotIn(self.product.id, ids)
        self.assertEqual(self.client.get(f'/api/products/{self.product.slug}/').status_code, 404)

    def test_not_in_category_products(self):
        category = self.product.category
        response = self.client.get(f'/api/products/categories/{category.slug}/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.product.id, [p['id'] for p in response.data['products']])


class ClientPageAPITest(BaseAPITest):
    def setUp(self):
        super().setUp()
        self.product = make_client_product()
        self.page = ClientPage.objects.create(name='Acme', slug='acme', allowed_emails='@acme.com')
        ClientPageItem.objects.create(page=self.page, product=self.product, flavour=Flavour.objects.first())
        self.allowed = User.objects.create_user(email='anna@acme.com', password='pw-12345!')
        self.outsider = User.objects.create_user(email='bob@other.com', password='pw-12345!')

    def test_anonymous_is_refused(self):
        self.assertIn(self.client.get('/api/clients/acme/').status_code, (401, 403))

    def test_outsider_gets_404(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get('/api/clients/acme/').status_code, 404)

    def test_inactive_page_gets_404(self):
        self.page.active = False
        self.page.save()
        self.client.force_authenticate(self.allowed)
        self.assertEqual(self.client.get('/api/clients/acme/').status_code, 404)

    def test_allowed_user_sees_page_and_products(self):
        self.client.force_authenticate(self.allowed)
        response = self.client.get('/api/clients/acme/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Acme')
        self.assertEqual(len(response.data['items']), 1)
        item = response.data['items'][0]
        self.assertEqual(item['product']['id'], self.product.id)
        self.assertEqual(item['product']['quantity_step'], 10)
        self.assertIsNotNone(item['flavour'])


class ClientOnlyCartTest(BaseAPITest):
    def setUp(self):
        super().setUp()
        self.product = make_client_product()
        page = ClientPage.objects.create(name='Acme', slug='acme', allowed_emails='@acme.com')
        ClientPageItem.objects.create(page=page, product=self.product)
        self.allowed = User.objects.create_user(email='anna@acme.com', password='pw-12345!')
        self.outsider = User.objects.create_user(email='bob@other.com', password='pw-12345!')

    def add(self, quantity, product=None):
        return self.client.post(
            '/api/carts/items/',
            {'product': (product or self.product).id, 'quantity': quantity},
            format='json',
        )

    def test_anonymous_cannot_add(self):
        response = self.add(10)
        self.assertEqual(response.status_code, 400)
        self.assertIn('product', response.data)

    def test_outsider_cannot_add(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.add(10).status_code, 400)

    def test_allowed_user_adds_in_tens(self):
        self.client.force_authenticate(self.allowed)
        response = self.add(20)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['items'][0]['quantity'], 20)
        self.assertEqual(response.data['base_total'], '36.00')

    def test_quantity_must_be_multiple_of_step(self):
        self.client.force_authenticate(self.allowed)
        response = self.add(13)
        self.assertEqual(response.status_code, 400)
        self.assertIn('quantity', response.data)

    def test_change_quantity_keeps_the_step(self):
        self.client.force_authenticate(self.allowed)
        item_id = self.add(10).data['items'][0]['id']
        url = f'/api/carts/items/{item_id}/change-quantity/'
        self.assertEqual(self.client.patch(url, {'quantity': 15}, format='json').status_code, 400)
        response = self.client.patch(url, {'quantity': 30}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['items'][0]['quantity'], 30)

    def test_inactive_page_blocks_purchase(self):
        ClientPage.objects.update(active=False)
        self.client.force_authenticate(self.allowed)
        self.assertEqual(self.add(10).status_code, 400)

    def test_normal_products_unaffected(self):
        response = self.add(3, product=Product.objects.get(pk=4))
        self.assertEqual(response.status_code, 201)


class LoadMclarenChocolatesCommandTest(BaseAPITest):
    def run_command(self, *args):
        out = StringIO()
        call_command('load_mclaren_chocolates', *args, stdout=out)
        return out.getvalue()

    def test_creates_page_and_four_hidden_products(self):
        self.run_command('--allow', '@mclaren.com')
        page = ClientPage.objects.get(slug='mclaren')
        self.assertEqual(page.allowed_emails, '@mclaren.com')
        products = Product.objects.filter(client_only=True)
        self.assertEqual(products.count(), 4)
        for product in products:
            self.assertEqual(product.quantity_step, 10)
            self.assertEqual(product.base_price, Decimal('1.80'))
            self.assertTrue(product.stripe_price_id.startswith('price_'))
            self.assertFalse(product.category.active)
        self.assertEqual(page.items.count(), 4)
        self.assertFalse(Product.objects.active().filter(client_only=True).exists())

    def test_is_idempotent_and_keeps_allowed_list(self):
        self.run_command('--allow', '@mclaren.com')
        self.run_command()
        self.assertEqual(Product.objects.filter(client_only=True).count(), 4)
        self.assertEqual(ClientPageItem.objects.count(), 4)
        self.assertEqual(ClientPage.objects.get(slug='mclaren').allowed_emails, '@mclaren.com')

    def test_dry_run_saves_nothing(self):
        self.run_command('--dry-run', '--allow', '@mclaren.com')
        self.assertFalse(ClientPage.objects.exists())
        self.assertFalse(Product.objects.filter(client_only=True).exists())
