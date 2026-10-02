"""Tests for the orders MCP server: the tools, the protocol and the endpoint."""
import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from addresses.models import Address
from allergens.models import Allergen
from carts.models import (
    Cart,
    CartItem,
    CartItemBoxCustomization,
    CartItemBoxFlavorSelection,
    CartItemPackCustomization,
)
from carts.tests.test_totals import make_product
from checkout.models import CheckoutSession
from checkout.tests import make_shipping_option
from flavours.models import Flavour, FlavourCategory
from orders.models import Order

from . import tools
from .protocol import handle_message

TOKEN = 'test-mcp-token'


class OrdersFixture(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.box = make_product('Box of 9', '14.99')
        self.pack = make_product('Taster Pack', '9.99')
        self.hot_chocolate = make_product('Hot Chocolate', '6.00')
        self.option = make_shipping_option('4.99')
        category = FlavourCategory.objects.create(name='Classics', slug='classics')
        self.caramel = Flavour.objects.create(name='Salted Caramel', slug='salted-caramel', category=category)
        self.praline = Flavour.objects.create(name='Praline', slug='praline', category=category)
        self.nuts = Allergen.objects.create(name='Nuts', slug='nuts')

    def make_order(self, email='guest@example.com', shipping_date=None, status='processing',
                   payment_status='paid', pickup_date=None, flavours=None, quantity=1,
                   gift_message=None, postcode='SW1A 1AA'):
        cart = Cart.objects.create(
            session_id=f'{email}-{Order.objects.count()}',
            shipping_date=shipping_date,
            pickup_date=pickup_date,
            gift_message=gift_message,
        )
        item = CartItem.objects.create(cart=cart, product=self.box, quantity=quantity)
        box = CartItemBoxCustomization.objects.create(
            cart_item=item, selection_type='PICK_AND_MIX' if flavours else 'RANDOM'
        )
        for flavour, qty in (flavours or {}).items():
            CartItemBoxFlavorSelection.objects.create(box_customization=box, flavor=flavour, quantity=qty)
        address = Address.objects.create(
            address_type='SHIPPING', first_name='Ada', last_name='Lovelace',
            street_address='1 Road', city='London', postcode=postcode,
        )
        session = CheckoutSession.objects.create(
            cart=cart, email=email, shipping_address=address, shipping_option=self.option,
        )
        session.payment_status = payment_status
        session.save()
        return Order.objects.create(checkout_session=session, status=status)


class ToolTests(OrdersFixture):
    def test_list_orders_filters_and_paginates(self):
        self.make_order(email='a@example.com')
        self.make_order(email='b@example.com')
        self.make_order(email='c@example.com', payment_status='pending')

        result = tools.list_orders(limit=1)
        self.assertEqual(result['total_matching'], 2)  # unpaid hidden by default
        self.assertTrue(result['has_more'])
        self.assertEqual(tools.list_orders(payment_status='any')['total_matching'], 3)
        self.assertEqual(tools.list_orders(search='b@example')['orders'][0]['email'], 'b@example.com')
        self.assertEqual(tools.list_orders(search='SW1A')['total_matching'], 2)

    def test_get_order_includes_flavours_address_and_history(self):
        first = self.make_order(email='repeat@example.com')
        order = self.make_order(
            email='repeat@example.com', flavours={self.caramel: 5, self.praline: 4},
            quantity=2, gift_message='Happy birthday',
        )

        detail = tools.get_order(order.order_id.lower())

        self.assertEqual(detail['order_id'], order.order_id)
        self.assertEqual(detail['shipping_address']['postcode'], 'SW1A 1AA')
        self.assertEqual(detail['gift_message'], 'Happy birthday')
        self.assertEqual(detail['shipping_option']['name'], 'Tracked 24')
        line = detail['lines'][0]
        self.assertEqual(line['quantity'], 2)
        self.assertEqual(
            line['flavours'],
            [{'flavour': 'Praline', 'chocolates': 8}, {'flavour': 'Salted Caramel', 'chocolates': 10}],
        )
        self.assertEqual(detail['other_paid_orders_from_customer'], [first.order_id])
        self.assertEqual(detail['totals']['products_after_discount'], '29.98')

    def test_get_order_unknown_id(self):
        with self.assertRaises(tools.ToolError):
            tools.get_order('CP25-NOPE')

    def test_shipping_queue_splits_due_overdue_and_undated(self):
        due = self.make_order(shipping_date=self.today)
        late = self.make_order(shipping_date=self.today - timedelta(days=2))
        undated = self.make_order()
        self.make_order(shipping_date=self.today + timedelta(days=1))  # future
        self.make_order(shipping_date=self.today, status='shipped')  # already gone
        self.make_order(shipping_date=self.today, payment_status='pending')  # not paid
        self.make_order(pickup_date=self.today)  # collected, not posted

        queue = tools.get_shipping_queue()

        self.assertEqual([o['order_id'] for o in queue['due_on_date']], [due.order_id])
        self.assertEqual([o['order_id'] for o in queue['overdue']], [late.order_id])
        self.assertEqual([o['order_id'] for o in queue['no_shipping_date']], [undated.order_id])
        self.assertEqual(queue['summary']['by_shipping_service'], {'Tracked 24': 3})

    def test_upcoming_shipments_calendar(self):
        tomorrow = self.today + timedelta(days=1)
        self.make_order(shipping_date=tomorrow, quantity=3)

        days = tools.get_upcoming_shipments(days=3)['days']

        self.assertEqual(len(days), 3)
        self.assertEqual(days[1]['date'], tomorrow.isoformat())
        self.assertEqual(days[1]['products'], {'Box of 9': 3})
        self.assertEqual(days[0]['orders'], 0)

    def test_pickup_orders(self):
        pickup = self.make_order(pickup_date=self.today)
        self.make_order(shipping_date=self.today)

        result = tools.get_pickup_orders()

        self.assertEqual([o['order_id'] for o in result['orders']], [pickup.order_id])

    def test_production_totals_adds_up_flavours_random_extras_and_allergens(self):
        a = self.make_order(shipping_date=self.today, flavours={self.caramel: 9}, quantity=2)
        b = self.make_order(shipping_date=self.today)  # random box of 9
        # A pack with a hot chocolate and a nut-free request.
        item = CartItem.objects.create(cart=b.checkout_session.cart, product=self.pack, quantity=1)
        pack = CartItemPackCustomization.objects.create(
            cart_item=item, selection_type='PICK_AND_MIX', hot_chocolate=self.hot_chocolate,
        )
        pack.allergens.add(self.nuts)
        CartItemBoxFlavorSelection.objects.create(pack_customization=pack, flavor=self.praline, quantity=9)
        self.make_order(shipping_date=self.today, status='cancelled', flavours={self.caramel: 9})

        totals = tools.get_production_totals(shipping_date_from=self.today.isoformat(),
                                             shipping_date_to=self.today.isoformat())

        self.assertEqual(sorted(totals['order_ids']), sorted([a.order_id, b.order_id]))
        self.assertEqual(totals['flavours'], [
            {'flavour': 'Salted Caramel', 'chocolates': 18},
            {'flavour': 'Praline', 'chocolates': 9},
        ])
        self.assertEqual(totals['random_chocolates'], 9)
        self.assertEqual(totals['pack_extras'], {'hot_chocolate': {'Hot Chocolate': 1}})
        self.assertEqual(totals['allergen_exclusions'][0]['exclude_allergens'], ['Nuts'])
        self.assertEqual(totals['products'][0], {'product': 'Box of 9', 'boxes': 3, 'chocolates': 27})

        by_id = tools.get_production_totals(order_ids=[a.order_id])
        self.assertEqual(by_id['orders_counted'], 1)

    def test_production_totals_needs_a_scope(self):
        with self.assertRaises(tools.ToolError):
            tools.get_production_totals()

    def test_sales_summary(self):
        self.make_order(email='a@example.com', quantity=2)
        self.make_order(email='a@example.com')
        self.make_order(email='b@example.com', payment_status='pending')

        summary = tools.get_sales_summary(group_by='month')

        self.assertEqual(summary['paid_orders'], 2)
        self.assertEqual(summary['unique_customers'], 1)
        self.assertEqual(summary['chocolates_sold'], 27)
        # 3 boxes at 14.99 plus 4.99 shipping on each order.
        self.assertEqual(summary['revenue_incl_shipping'], str(Decimal('14.99') * 3 + Decimal('4.99') * 2))

    def test_customer_orders_and_catalogue(self):
        self.make_order(email='Repeat@Example.com')
        self.assertEqual(tools.get_customer_orders('repeat@example.com')['paid_orders'], 1)
        self.assertEqual(tools.list_shipping_options()[0]['name'], 'Tracked 24')
        self.assertIn('Box of 9', [p['name'] for p in tools.list_products()])

    def test_bad_date_is_a_tool_error(self):
        with self.assertRaises(tools.ToolError):
            tools.list_orders(created_from='02/10/2026')


class ProtocolTests(OrdersFixture):
    def rpc(self, method, params=None, msg_id=1):
        return handle_message({'jsonrpc': '2.0', 'id': msg_id, 'method': method, 'params': params or {}})

    def test_initialize_negotiates_version(self):
        result = self.rpc('initialize', {'protocolVersion': '2025-03-26'})['result']
        self.assertEqual(result['protocolVersion'], '2025-03-26')
        self.assertIn('tools', result['capabilities'])
        unknown = self.rpc('initialize', {'protocolVersion': '1999-01-01'})['result']
        self.assertEqual(unknown['protocolVersion'], '2025-06-18')

    def test_notifications_get_no_reply(self):
        self.assertIsNone(handle_message({'jsonrpc': '2.0', 'method': 'notifications/initialized'}))

    def test_tools_list_exposes_every_tool(self):
        names = {t['name'] for t in self.rpc('tools/list')['result']['tools']}
        self.assertEqual(names, set(tools.TOOLS))

    def test_tools_call_returns_json_text(self):
        order = self.make_order()
        result = self.rpc('tools/call', {'name': 'get_order', 'arguments': {'order_id': order.order_id}})['result']
        self.assertFalse(result['isError'])
        self.assertEqual(json.loads(result['content'][0]['text'])['order_id'], order.order_id)

    def test_tool_errors_are_reported_not_raised(self):
        result = self.rpc('tools/call', {'name': 'get_order', 'arguments': {'order_id': 'NOPE'}})['result']
        self.assertTrue(result['isError'])
        result = self.rpc('tools/call', {'name': 'list_orders', 'arguments': {'bogus': 1}})['result']
        self.assertTrue(result['isError'])
        result = self.rpc('tools/call', {'name': 'get_order', 'arguments': {}})['result']
        self.assertTrue(result['isError'])

    def test_unknown_tool_and_method(self):
        self.assertEqual(self.rpc('tools/call', {'name': 'drop_tables'})['error']['code'], -32602)
        self.assertEqual(self.rpc('resources/list')['error']['code'], -32601)


@override_settings(MCP_API_TOKEN=TOKEN)
class EndpointTests(OrdersFixture):
    def post(self, body, token=TOKEN, path='/api/mcp/'):
        headers = {'HTTP_AUTHORIZATION': f'Bearer {token}'} if token else {}
        return self.client.post(path, data=json.dumps(body), content_type='application/json', **headers)

    def test_requires_the_token(self):
        body = {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}
        self.assertEqual(self.post(body, token=None).status_code, 401)
        self.assertEqual(self.post(body, token='wrong').status_code, 401)
        self.assertEqual(self.post(body).status_code, 200)

    def test_token_in_path(self):
        body = {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}
        self.assertEqual(self.post(body, token=None, path=f'/api/mcp/{TOKEN}/').status_code, 200)
        self.assertEqual(self.post(body, token=None, path='/api/mcp/wrong/').status_code, 401)

    @override_settings(MCP_API_TOKEN='')
    def test_disabled_without_a_token(self):
        response = self.post({'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}, token='')
        self.assertEqual(response.status_code, 503)

    def test_full_round_trip(self):
        order = self.make_order(shipping_date=timezone.localdate())
        init = self.post({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                          'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                                     'clientInfo': {'name': 'test', 'version': '1'}}})
        self.assertEqual(init.json()['result']['serverInfo']['name'], 'casspea-orders')
        self.assertEqual(self.post({'jsonrpc': '2.0', 'method': 'notifications/initialized'}).status_code, 202)

        call = self.post({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                          'params': {'name': 'get_shipping_queue', 'arguments': {}}})
        queue = json.loads(call.json()['result']['content'][0]['text'])
        self.assertEqual(queue['due_on_date'][0]['order_id'], order.order_id)

    def test_get_is_not_allowed_and_bad_json_is_rejected(self):
        self.assertEqual(self.client.get('/api/mcp/', HTTP_AUTHORIZATION=f'Bearer {TOKEN}').status_code, 405)
        response = self.client.post('/api/mcp/', data='{nope', content_type='application/json',
                                    HTTP_AUTHORIZATION=f'Bearer {TOKEN}')
        self.assertEqual(response.status_code, 400)
