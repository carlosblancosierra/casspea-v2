"""The API contract with the Next.js storefront (next-casspea).

Two halves:

* ``contract/frontend-api-calls.json`` is copied from next-casspea, where a
  test records every request the storefront can send. Each one must still
  resolve to a view here that accepts that HTTP method.
* ``contract/responses/*.json`` are real responses for the endpoints the shop
  is built on. The storefront's tests use them as fixtures; this suite checks
  that the live responses still have the same shape (keys and value types).

A redesign of the storefront should not need a single backend change. If one
of these tests fails, the API changed under the frontend: either revert, or
regenerate, review the diff and copy the files to next-casspea/contract/:

    UPDATE_CONTRACT=1 python manage.py test erp.tests.test_frontend_contract --settings=erp.settings_test
"""
import json
import os
import re
from pathlib import Path
from unittest import expectedFailure

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.urls import Resolver404, resolve
from rest_framework.test import APIClient

from clients.models import ClientPageItem
from clients.tests.test_clients import CODE, make_client_product, make_page

CONTRACT_DIR = Path(settings.BASE_DIR) / 'contract'
RESPONSES_DIR = CONTRACT_DIR / 'responses'
UPDATING = os.environ.get('UPDATE_CONTRACT') == '1'

# Calls the storefront makes that the API cannot answer. Each one is a known
# bug (IDs from next-casspea/docs/plan-rediseno-seguro.md). Remove the entry
# together with the fix, and delete its expected-failure test below.
KNOWN_GAPS = {
    ('POST', '/api/personalized/send-request/'):
        'BUG-05: no such endpoint, so personalised-chocolate requests are lost',
}


def load_frontend_calls():
    with open(CONTRACT_DIR / 'frontend-api-calls.json') as f:
        return json.load(f)


def resolve_call(method, path):
    """The view Django would route this call to, or None."""
    path = path.split('?')[0]
    try:
        return resolve(path)
    except Resolver404:
        # CommonMiddleware answers a GET without its trailing slash with a
        # redirect to path + '/'. A POST would lose its body, so only GET.
        if method == 'GET' and not path.endswith('/'):
            try:
                return resolve(path + '/')
            except Resolver404:
                pass
    return None


def allowed_methods(match):
    """HTTP methods the resolved view answers, or None if it cannot be told."""
    actions = getattr(match.func, 'actions', None)
    if actions:  # a ViewSet route: the router maps each method to an action
        return {method.upper() for method in actions}
    view_class = getattr(match.func, 'cls', None) or getattr(match.func, 'view_class', None)
    if view_class is not None:
        return {
            method.upper() for method in view_class.http_method_names
            if method != 'options' and hasattr(view_class, method)
        }
    return None


class FrontendCallsResolveTest(TestCase):
    def test_every_frontend_call_reaches_a_view_that_accepts_its_method(self):
        for call in load_frontend_calls():
            method, path = call['method'], call['path']
            if (method, path.split('?')[0]) in KNOWN_GAPS:
                continue
            with self.subTest(endpoint=call['endpoint'], call=f'{method} {path}'):
                match = resolve_call(method, path)
                self.assertIsNotNone(match, f'{method} {path} does not resolve to any view')
                methods = allowed_methods(match)
                if methods is not None:
                    self.assertIn(method, methods, f'{method} {path} resolves, but the view only answers {sorted(methods)}')

    def test_known_gaps_are_still_called_by_the_frontend(self):
        called = {(call['method'], call['path'].split('?')[0]) for call in load_frontend_calls()}
        self.assertEqual([gap for gap in KNOWN_GAPS if gap not in called], [])

    @expectedFailure
    def test_bug_05_personalised_request_endpoint_exists(self):
        self.assertIsNotNone(resolve_call('POST', '/api/personalized/send-request/'))


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------

ISO_DATETIME = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}')


def normalise(value):
    """What gets written to contract/responses: lists cut to one element (the
    shape is all that is compared) and timestamps frozen so regenerating the
    files does not produce a noisy diff."""
    if isinstance(value, dict):
        return {key: normalise(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalise(value[0])] if value else []
    if isinstance(value, str) and ISO_DATETIME.match(value):
        return '2026-01-01T00:00:00Z'
    return value


def shape(value):
    """Keys and JSON types, recursively; a list is described by its first item."""
    if isinstance(value, dict):
        return {key: shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, (int, float)):
        return 'number'
    return 'string'


class ResponseShapeTest(TestCase):
    """The responses the storefront is built on keep their shape."""

    fixtures = [
        'initial_discounts.json',
        'initial_product_category.json',
        'initial_products.json',
        'initial_allergens.json',
        'initial_flavour_categories.json',
        'initial_flavours.json',
        'initial_shipping.json',
    ]

    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def assertMatchesContract(self, name, response, status=200):
        self.assertEqual(response.status_code, status, response.content[:500])
        body = response.json()
        path = RESPONSES_DIR / f'{name}.json'
        if UPDATING:
            RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(normalise(body), indent=2, ensure_ascii=False) + '\n')
            return
        expected = json.loads(path.read_text())
        self.assertEqual(
            shape(body), shape(expected),
            f'{name}: the response shape changed. If that is deliberate, regenerate '
            f'contract/responses with UPDATE_CONTRACT=1 and copy it to next-casspea/contract/responses.',
        )

    def add_box(self):
        return self.client.post('/api/carts/items/', {
            'product': 1,
            'quantity': 1,
            'box_customization': {'selection_type': 'RANDOM', 'allergens': []},
        }, format='json')

    def test_catalogue(self):
        self.assertMatchesContract('products-list', self.client.get('/api/products/'))
        slug = self.client.get('/api/products/').json()[0]['slug']
        self.assertMatchesContract('product-detail', self.client.get(f'/api/products/{slug}/'))
        self.assertMatchesContract('product-categories', self.client.get('/api/products/categories/'))
        self.assertMatchesContract('flavours', self.client.get('/api/flavours/'))
        self.assertMatchesContract('shipping-options', self.client.get('/api/shipping/options/'))
        self.assertMatchesContract('store-status', self.client.get('/api/checkout/store-status/'))

    def test_cart(self):
        self.assertMatchesContract('cart-empty', self.client.get('/api/carts/'))
        # The whole cart comes back, not the line that was added (see BUG-04).
        self.assertMatchesContract('cart-item-created', self.add_box(), status=201)
        self.assertMatchesContract('cart-updated', self.client.post(
            '/api/carts/', {'gift_message': 'Happy birthday'}, format='json'))

    def test_checkout_session(self):
        self.add_box()
        self.assertMatchesContract('checkout-session-email', self.client.post(
            '/api/checkout/session/', {'email': 'guest@example.com'}, format='json'))
        response = self.client.post('/api/addresses/', {'shipping_address': {
            'address_type': 'SHIPPING',
            'full_name': 'Ada Lovelace',
            'first_name': 'Ada',
            'last_name': 'Lovelace',
            'phone': '07700900123',
            'street_address': '1 Test Street',
            'city': 'London',
            'postcode': 'SW1A 1AA',
            'country': 'United Kingdom',
        }}, format='json')
        self.assertMatchesContract('address-created', response, status=201)
        session_id = self.client.get('/api/checkout/session/').json()['id']
        self.assertMatchesContract('checkout-session-shipping-option', self.client.post(
            f'/api/checkout/session/{session_id}/shipping-option/', {'shipping_option_id': 2}, format='json'))
        self.assertMatchesContract('checkout-session', self.client.get('/api/checkout/session/'))

    def test_client_page(self):
        page = make_page()
        ClientPageItem.objects.create(page=page, product=make_client_product())
        self.assertMatchesContract('client-page-locked', self.client.get('/api/clients/acme/'))
        self.assertMatchesContract('client-page-unlocked', self.client.post(
            '/api/clients/acme/unlock/', {'code': CODE}, format='json'))
