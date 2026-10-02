"""Read-only order tools exposed over MCP.

Every tool is a plain function that takes keyword arguments (validated against
the JSON schema it is registered with) and returns something json.dumps can
handle. They read the same data the orders backend shows — dates, products,
flavours, addresses, shipping service, tracking — so an assistant can answer
"what do we post on Friday?" or "how many Salted Caramel do we need?" without
anyone exporting a CSV.

Nothing here writes. Marking orders shipped, sending tracking emails and
creating Royal Mail labels stay in the backend, where a person does them.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.utils import timezone

from orders.models import Order
from orders.views import ORDER_PREFETCH_RELATED, ORDER_SELECT_RELATED
from products.models import Product
from shipping.models import ShippingOption


class ToolError(Exception):
    """A problem with the caller's input, reported back as a tool error."""


# Statuses that still need someone to do something before the box leaves.
OPEN_STATUSES = ('processing', 'pending')
# Statuses that never reach the kitchen or the post office.
DEAD_STATUSES = ('cancelled', 'refunded')

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
# Ceiling for tools that return every matching order with full detail.
MAX_FULL_ORDERS = 500

SELECT_RELATED = ORDER_SELECT_RELATED + (
    'checkout_session__cart__user',
    'checkout_session__shipping_option__company',
)

PREFETCH_RELATED = ORDER_PREFETCH_RELATED + (
    'checkout_session__cart__items__box_customization__flavor_selections__flavor',
    'checkout_session__cart__items__pack_customization__flavor_selections_pack__flavor',
    'checkout_session__cart__items__pack_customization__hot_chocolate',
    'checkout_session__cart__items__pack_customization__gift_card',
    'checkout_session__cart__items__pack_customization__chocolate_bark',
    'checkout_session__cart__discount__exclusions',
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _orders():
    return (
        Order.objects
        .select_related(*SELECT_RELATED)
        .prefetch_related(*PREFETCH_RELATED)
    )


def _parse_date(value, field):
    if value in (None, ''):
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except ValueError:
        raise ToolError(f"'{field}' must be a date in YYYY-MM-DD format, got {value!r}.")


def _start_of(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def _filter_created(qs, created_from, created_to):
    start = _parse_date(created_from, 'created_from')
    end = _parse_date(created_to, 'created_to')
    if start:
        qs = qs.filter(created__gte=_start_of(start))
    if end:
        qs = qs.filter(created__lt=_start_of(end + timedelta(days=1)))
    return qs


def _filter_shipping_date(qs, shipping_from, shipping_to):
    start = _parse_date(shipping_from, 'shipping_date_from')
    end = _parse_date(shipping_to, 'shipping_date_to')
    if start:
        qs = qs.filter(checkout_session__cart__shipping_date__gte=start)
    if end:
        qs = qs.filter(checkout_session__cart__shipping_date__lte=end)
    return qs


def _limit(value, default=DEFAULT_LIMIT, maximum=MAX_LIMIT):
    if value is None:
        return default
    return max(1, min(int(value), maximum))


def _money(value):
    if value is None:
        return None
    return str(Decimal(value).quantize(Decimal('0.01')))


def _iso(value):
    return value.isoformat() if value else None


def _related(obj, name):
    """Reverse one-to-one access that returns None instead of raising."""
    try:
        return getattr(obj, name)
    except ObjectDoesNotExist:
        return None


def _email(order):
    session = order.checkout_session
    if session.email:
        return session.email
    user = session.cart.user
    return user.email if user else ''


def _customer_name(address):
    if not address:
        return ''
    name = ' '.join(p for p in [address.first_name, address.last_name] if p).strip()
    return name or (address.full_name or '')


def _address(address):
    if not address:
        return None
    return {
        'name': _customer_name(address),
        'phone': address.phone or None,
        'street_address': address.street_address,
        'street_address2': address.street_address2 or None,
        'city': address.city,
        'county': address.county or None,
        'postcode': address.postcode,
        'country': address.country,
    }


def _shipping_option(option):
    if not option:
        return None
    return {
        'id': option.id,
        'name': option.name,
        'company': option.company.name if option.company_id else None,
        'service_code': option.service_code,
        'guaranteed': option.guaranteed,
        'estimated_days': [option.estimated_days_min, option.estimated_days_max],
        'price': _money(option.price),
    }


def _custom_option_label(item):
    key = item.selected_custom_option_key
    if not key:
        return None
    for option in item.product.custom_options or []:
        if isinstance(option, dict) and option.get('key') == key:
            return option.get('label') or key
    return key


# ---------------------------------------------------------------------------
# Line items and flavours
# ---------------------------------------------------------------------------

def _flavour_breakdown(item):
    """What goes inside one cart line, chocolate by chocolate.

    Returns (selection_type, {flavour_name: chocolates}, random_chocolates,
    allergen_exclusions, extras). Counts are for the whole line, i.e. already
    multiplied by the line quantity.

    Mirrors orders.views.get_monthly_flavour_data: a RANDOM customisation with
    no picked flavours is `units_per_box` random chocolates per box; picked
    flavours count as chosen; a line with no customisation has no breakdown.
    """
    flavours = Counter()
    random_chocolates = 0
    allergens = []
    extras = {}
    selection_type = None

    box = _related(item, 'box_customization')
    pack = _related(item, 'pack_customization')

    for custom, selections_name in ((box, 'flavor_selections'), (pack, 'flavor_selections_pack')):
        if not custom:
            continue
        selection_type = custom.selection_type or selection_type
        selections = list(getattr(custom, selections_name).all())
        allergens += [a.name for a in custom.allergens.all()]
        if selections:
            for selection in selections:
                flavours[selection.flavor.name] += selection.quantity * item.quantity
        elif custom.selection_type == 'RANDOM':
            random_chocolates += item.product.units_per_box * item.quantity

    if pack:
        for field in ('hot_chocolate', 'gift_card', 'chocolate_bark'):
            extra = getattr(pack, field)
            if extra:
                extras[field] = extra.name

    return selection_type, flavours, random_chocolates, sorted(set(allergens)), extras


def _line(item):
    selection_type, flavours, random_chocolates, allergens, extras = _flavour_breakdown(item)
    product = item.product
    line = {
        'product': product.name,
        'product_slug': product.slug,
        'quantity': item.quantity,
        'units_per_box': product.units_per_box,
        'chocolates': product.units_per_box * item.quantity,
        'unit_price': _money(product.current_price),
        'line_total': _money(item.discounted_price),
        'selection_type': selection_type,
        'flavours': [
            {'flavour': name, 'chocolates': qty}
            for name, qty in sorted(flavours.items())
        ],
        'random_chocolates': random_chocolates,
    }
    option = _custom_option_label(item)
    if option:
        line['custom_option'] = option
    if allergens:
        line['exclude_allergens'] = allergens
    if extras:
        line['pack_extras'] = extras
    if product.fixed_dispatch_date:
        line['fixed_dispatch_date'] = _iso(product.fixed_dispatch_date)
    return line


# ---------------------------------------------------------------------------
# Order representations
# ---------------------------------------------------------------------------

def _order_summary(order):
    session = order.checkout_session
    cart = session.cart
    items = list(cart.items.all())
    address = session.shipping_address
    option = session.shipping_option
    return {
        'order_id': order.order_id,
        'created': _iso(order.created),
        'status': order.status,
        'payment_status': session.payment_status,
        'customer_name': _customer_name(address),
        'email': _email(order),
        'postcode': address.postcode if address else None,
        'shipping_date': _iso(cart.shipping_date),
        'pickup_date': _iso(cart.pickup_date),
        'pickup_time': cart.pickup_time or None,
        'shipping_service': option.name if option else None,
        'tracking_number': order.tracking_number,
        'royal_mail_order_id': order.shipping_order_id,
        'shipped': _iso(order.shipped),
        'delivered': _iso(order.delivered),
        'items': ', '.join(f'{i.quantity} x {i.product.name}' for i in items),
        'item_count': sum(i.quantity for i in items),
        'has_gift_message': bool(cart.gift_message),
        'total': _money(session.total_with_shipping),
    }


def _order_detail(order):
    session = order.checkout_session
    cart = session.cart
    option = session.shipping_option
    detail = _order_summary(order)
    detail.update({
        'phone': session.phone or (session.shipping_address.phone if session.shipping_address else None),
        'shipping_address': _address(session.shipping_address),
        'billing_address': _address(session.billing_address),
        'shipping_option': _shipping_option(option),
        'tracking_url': (
            option.company.track_url
            if option and option.company_id and option.company.track_url else None
        ),
        'gift_message': cart.gift_message or None,
        'lines': [_line(item) for item in cart.items.all()],
        'discount_code': cart.discount.code if cart.discount else None,
        'totals': {
            'products_before_discount': _money(cart.base_total),
            'products_after_discount': _money(cart.discounted_total),
            'discount_savings': _money(cart.total_savings),
            'shipping': _money(session.shipping_cost_pounds),
            'total': _money(session.total_with_shipping),
        },
        'stripe_payment_intent': session.stripe_payment_intent,
        'status_history': [
            {'status': h.status, 'notes': h.notes, 'at': _iso(h.created)}
            for h in order.status_history.all()
        ],
    })
    return detail


def _search(qs, search):
    if not search:
        return qs
    return qs.filter(
        Q(order_id__icontains=search)
        | Q(checkout_session__email__icontains=search)
        | Q(checkout_session__cart__user__email__icontains=search)
        | Q(tracking_number__icontains=search)
        | Q(shipping_order_id__icontains=search)
        | Q(checkout_session__shipping_address__first_name__icontains=search)
        | Q(checkout_session__shipping_address__last_name__icontains=search)
        | Q(checkout_session__shipping_address__full_name__icontains=search)
        | Q(checkout_session__shipping_address__postcode__icontains=search)
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def list_orders(created_from=None, created_to=None, shipping_date_from=None,
                shipping_date_to=None, status=None, payment_status='paid',
                search=None, shipping_option_id=None, limit=None, offset=0):
    qs = _orders()
    qs = _filter_created(qs, created_from, created_to)
    qs = _filter_shipping_date(qs, shipping_date_from, shipping_date_to)
    if status:
        qs = qs.filter(status=status)
    if payment_status and payment_status != 'any':
        qs = qs.filter(checkout_session__payment_status=payment_status)
    if shipping_option_id:
        qs = qs.filter(checkout_session__shipping_option_id=shipping_option_id)
    qs = _search(qs, search).order_by('-created')

    limit = _limit(limit)
    offset = max(0, int(offset or 0))
    total = qs.count()
    rows = [_order_summary(o) for o in qs[offset:offset + limit]]
    return {
        'total_matching': total,
        'offset': offset,
        'returned': len(rows),
        'has_more': offset + len(rows) < total,
        'orders': rows,
    }


def get_order(order_id):
    order = _orders().filter(order_id__iexact=order_id.strip()).first()
    if not order:
        raise ToolError(f'No order with id {order_id!r}.')
    detail = _order_detail(order)
    email = _email(order)
    detail['other_paid_orders_from_customer'] = list(
        Order.objects
        .filter(
            Q(checkout_session__email__iexact=email)
            | Q(checkout_session__cart__user__email__iexact=email),
            checkout_session__payment_status='paid',
        )
        .exclude(pk=order.pk)
        .order_by('-created')
        .values_list('order_id', flat=True)
    ) if email else []
    return detail


def get_customer_orders(email, limit=None):
    email = email.strip()
    if not email:
        raise ToolError("'email' is required.")
    qs = _orders().filter(
        Q(checkout_session__email__iexact=email)
        | Q(checkout_session__cart__user__email__iexact=email)
    ).order_by('-created')
    orders = list(qs[:_limit(limit)])
    paid = [o for o in orders if o.checkout_session.payment_status == 'paid']
    return {
        'email': email,
        'orders_found': len(orders),
        'paid_orders': len(paid),
        'total_spent': _money(sum((o.checkout_session.total_with_shipping for o in paid), Decimal('0'))),
        'orders': [_order_summary(o) for o in orders],
    }


def _open_orders():
    return (
        _orders()
        .filter(
            checkout_session__payment_status='paid',
            status__in=OPEN_STATUSES,
            shipped__isnull=True,
        )
        .order_by('checkout_session__cart__shipping_date', 'created')
    )


def _service_counts(orders):
    counts = Counter(
        (o.checkout_session.shipping_option.name if o.checkout_session.shipping_option else 'No shipping option')
        for o in orders
    )
    return dict(counts.most_common())


def get_shipping_queue(date=None, include_overdue=True, include_undated=True):
    day = _parse_date(date, 'date') or timezone.localdate()
    base = _open_orders().filter(checkout_session__cart__pickup_date__isnull=True)

    due = list(base.filter(checkout_session__cart__shipping_date=day)[:MAX_FULL_ORDERS])
    overdue = list(
        base.filter(checkout_session__cart__shipping_date__lt=day)[:MAX_FULL_ORDERS]
    ) if include_overdue else []
    undated = list(
        base.filter(checkout_session__cart__shipping_date__isnull=True)[:MAX_FULL_ORDERS]
    ) if include_undated else []

    everything = due + overdue + undated
    return {
        'date': day.isoformat(),
        'summary': {
            'due_on_date': len(due),
            'overdue': len(overdue),
            'no_shipping_date': len(undated),
            'by_shipping_service': _service_counts(everything),
            'boxes': sum(i.quantity for o in everything for i in o.checkout_session.cart.items.all()),
        },
        'due_on_date': [_order_detail(o) for o in due],
        'overdue': [_order_detail(o) for o in overdue],
        'no_shipping_date': [_order_detail(o) for o in undated],
    }


def get_upcoming_shipments(date_from=None, days=7):
    start = _parse_date(date_from, 'date_from') or timezone.localdate()
    days = max(1, min(int(days or 7), 60))
    end = start + timedelta(days=days - 1)
    orders = list(
        _open_orders()
        .filter(
            checkout_session__cart__pickup_date__isnull=True,
            checkout_session__cart__shipping_date__range=(start, end),
        )
    )
    by_day = defaultdict(list)
    for order in orders:
        by_day[order.checkout_session.cart.shipping_date].append(order)

    calendar = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        day_orders = by_day.get(day, [])
        products = Counter()
        for o in day_orders:
            for item in o.checkout_session.cart.items.all():
                products[item.product.name] += item.quantity
        calendar.append({
            'date': day.isoformat(),
            'weekday': day.strftime('%A'),
            'orders': len(day_orders),
            'boxes': sum(products.values()),
            'products': dict(products.most_common()),
            'by_shipping_service': _service_counts(day_orders),
            'order_ids': [o.order_id for o in day_orders],
        })
    return {'from': start.isoformat(), 'to': end.isoformat(), 'days': calendar}


def get_pickup_orders(date_from=None, date_to=None, include_collected=False):
    start = _parse_date(date_from, 'date_from') or timezone.localdate()
    end = _parse_date(date_to, 'date_to') or start
    qs = (
        _orders()
        .filter(
            checkout_session__payment_status='paid',
            checkout_session__cart__pickup_date__range=(start, end),
        )
        .exclude(status__in=DEAD_STATUSES)
        .order_by('checkout_session__cart__pickup_date', 'checkout_session__cart__pickup_time')
    )
    if not include_collected:
        qs = qs.filter(status__in=OPEN_STATUSES)
    orders = list(qs[:MAX_FULL_ORDERS])
    return {
        'from': start.isoformat(),
        'to': end.isoformat(),
        'count': len(orders),
        'orders': [_order_detail(o) for o in orders],
    }


def get_production_totals(order_ids=None, shipping_date_from=None, shipping_date_to=None,
                          created_from=None, created_to=None, only_open=True):
    qs = _orders().filter(checkout_session__payment_status='paid').exclude(status__in=DEAD_STATUSES)
    if order_ids:
        wanted = [o.strip().upper() for o in order_ids if o and o.strip()][:MAX_FULL_ORDERS]
        qs = qs.filter(order_id__in=wanted)
    else:
        if not any([shipping_date_from, shipping_date_to, created_from, created_to]):
            raise ToolError(
                'Give order_ids, or a shipping date range, or a created date range — '
                'otherwise this would add up every order ever placed.'
            )
        qs = _filter_shipping_date(qs, shipping_date_from, shipping_date_to)
        qs = _filter_created(qs, created_from, created_to)
        if only_open:
            qs = qs.filter(status__in=OPEN_STATUSES, shipped__isnull=True)

    orders = list(qs.order_by('created')[:MAX_FULL_ORDERS])

    products = defaultdict(lambda: {'boxes': 0, 'chocolates': 0})
    flavours = Counter()
    random_chocolates = 0
    extras = defaultdict(Counter)
    allergen_notes = []
    gift_messages = 0

    for order in orders:
        cart = order.checkout_session.cart
        if cart.gift_message:
            gift_messages += 1
        for item in cart.items.all():
            products[item.product.name]['boxes'] += item.quantity
            products[item.product.name]['chocolates'] += item.product.units_per_box * item.quantity
            _, line_flavours, line_random, allergens, line_extras = _flavour_breakdown(item)
            flavours.update(line_flavours)
            random_chocolates += line_random
            for kind, name in line_extras.items():
                extras[kind][name] += item.quantity
            if allergens:
                allergen_notes.append({
                    'order_id': order.order_id,
                    'product': item.product.name,
                    'quantity': item.quantity,
                    'exclude_allergens': allergens,
                })

    return {
        'orders_counted': len(orders),
        'order_ids': [o.order_id for o in orders],
        'products': [
            {'product': name, **counts}
            for name, counts in sorted(products.items(), key=lambda kv: -kv[1]['boxes'])
        ],
        'flavours': [
            {'flavour': name, 'chocolates': qty} for name, qty in flavours.most_common()
        ],
        'picked_flavour_chocolates': sum(flavours.values()),
        'random_chocolates': random_chocolates,
        'pack_extras': {kind: dict(counter) for kind, counter in extras.items()},
        'allergen_exclusions': allergen_notes,
        'orders_with_gift_message': gift_messages,
    }


def get_sales_summary(created_from=None, created_to=None, group_by='day'):
    end = _parse_date(created_to, 'created_to') or timezone.localdate()
    start = _parse_date(created_from, 'created_from') or (end - timedelta(days=29))
    if group_by not in ('day', 'week', 'month'):
        raise ToolError("'group_by' must be one of day, week, month.")

    qs = _filter_created(_orders(), start, end).filter(checkout_session__payment_status='paid')
    orders = list(qs.order_by('created'))

    revenue = Decimal('0')
    shipping = Decimal('0')
    statuses = Counter()
    services = Counter()
    discount_codes = Counter()
    products = defaultdict(lambda: {'boxes': 0, 'revenue': Decimal('0')})
    periods = defaultdict(lambda: {'orders': 0, 'revenue': Decimal('0')})
    chocolates = 0
    customers = set()

    for order in orders:
        session = order.checkout_session
        cart = session.cart
        total = session.total_with_shipping
        revenue += total
        shipping += session.shipping_cost_pounds
        statuses[order.status] += 1
        services[session.shipping_option.name if session.shipping_option else 'No shipping option'] += 1
        if cart.discount:
            discount_codes[cart.discount.code] += 1
        customers.add(_email(order).lower())

        local = timezone.localtime(order.created).date()
        if group_by == 'day':
            key = local.isoformat()
        elif group_by == 'week':
            key = (local - timedelta(days=local.weekday())).isoformat()
        else:
            key = local.strftime('%Y-%m')
        periods[key]['orders'] += 1
        periods[key]['revenue'] += total

        for item in cart.items.all():
            products[item.product.name]['boxes'] += item.quantity
            products[item.product.name]['revenue'] += Decimal(item.discounted_price)
            chocolates += item.product.units_per_box * item.quantity

    return {
        'from': start.isoformat(),
        'to': end.isoformat(),
        'paid_orders': len(orders),
        'unique_customers': len(customers),
        'revenue_incl_shipping': _money(revenue),
        'shipping_charged': _money(shipping),
        'average_order_value': _money(revenue / len(orders)) if orders else None,
        'chocolates_sold': chocolates,
        'orders_by_status': dict(statuses),
        'orders_by_shipping_service': dict(services.most_common()),
        'discount_codes_used': dict(discount_codes.most_common()),
        'products': [
            {'product': name, 'boxes': v['boxes'], 'revenue': _money(v['revenue'])}
            for name, v in sorted(products.items(), key=lambda kv: -kv[1]['boxes'])
        ],
        f'by_{group_by}': [
            {'period': key, 'orders': v['orders'], 'revenue': _money(v['revenue'])}
            for key, v in sorted(periods.items())
        ],
    }


def list_shipping_options(include_inactive=False):
    qs = ShippingOption.objects.select_related('company').order_by('price')
    if not include_inactive:
        qs = qs.filter(active=True)
    return [
        {
            **_shipping_option(option),
            'active': option.active,
            'disabled': option.disabled,
            'disabled_reason': option.disabled_reason or None,
        }
        for option in qs
    ]


def list_products(include_inactive=False):
    qs = Product.objects.select_related('category').order_by('category__order', 'name')
    if not include_inactive:
        qs = qs.filter(active=True)
    return [
        {
            'id': p.id,
            'name': p.name,
            'slug': p.slug,
            'category': p.category.name,
            'price': _money(p.current_price),
            'units_per_box': p.units_per_box,
            'weight_g': p.weight,
            'active': p.active,
            'sold_out': p.sold_out,
            'preorder': p.preorder,
            'preorder_finish_date': _iso(p.preorder_finish_date),
            'fixed_dispatch_date': _iso(p.fixed_dispatch_date),
            'pickup_only': p.pickup_only,
        }
        for p in qs
    ]


# ---------------------------------------------------------------------------
# Registry: name -> (function, description, JSON schema)
# ---------------------------------------------------------------------------

_DATE = {'type': 'string', 'description': 'Date as YYYY-MM-DD.'}

TOOLS = {
    'list_orders': (
        list_orders,
        'List orders, newest first, as one row each (customer, postcode, products, '
        'shipping date, service, tracking, status, total). Filter by order date, '
        'shipping date, status, payment status or free-text search (order id, email, '
        'name, postcode, tracking number). Paginate with limit/offset.',
        {
            'type': 'object',
            'properties': {
                'created_from': {**_DATE, 'description': 'Placed on or after this date (YYYY-MM-DD).'},
                'created_to': {**_DATE, 'description': 'Placed on or before this date (YYYY-MM-DD).'},
                'shipping_date_from': {**_DATE, 'description': 'Posting date on or after (YYYY-MM-DD).'},
                'shipping_date_to': {**_DATE, 'description': 'Posting date on or before (YYYY-MM-DD).'},
                'status': {
                    'type': 'string',
                    'enum': ['pending', 'processing', 'shipped', 'delivered', 'cancelled', 'refunded'],
                },
                'payment_status': {
                    'type': 'string',
                    'enum': ['paid', 'pending', 'failed', 'cancelled', 'any'],
                    'default': 'paid',
                },
                'search': {'type': 'string'},
                'shipping_option_id': {'type': 'integer', 'description': 'From list_shipping_options.'},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': MAX_LIMIT, 'default': DEFAULT_LIMIT},
                'offset': {'type': 'integer', 'minimum': 0, 'default': 0},
            },
            'additionalProperties': False,
        },
    ),
    'get_order': (
        get_order,
        'Everything about one order: customer, phone, shipping and billing address, '
        'gift message, each product with its flavours (chocolates per flavour), random '
        'chocolates, allergens to exclude, pack extras, shipping service, tracking, '
        'Royal Mail id, totals, discount and status history.',
        {
            'type': 'object',
            'properties': {'order_id': {'type': 'string', 'description': 'e.g. CP25-B4K9'}},
            'required': ['order_id'],
            'additionalProperties': False,
        },
    ),
    'get_customer_orders': (
        get_customer_orders,
        "A customer's order history by email, with how much they have spent.",
        {
            'type': 'object',
            'properties': {
                'email': {'type': 'string'},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': MAX_LIMIT},
            },
            'required': ['email'],
            'additionalProperties': False,
        },
    ),
    'get_shipping_queue': (
        get_shipping_queue,
        'What has to be posted on a day (default today): paid orders not yet shipped '
        'whose posting date is that day, plus overdue ones and ones with no posting '
        'date. Full detail for packing: address, products, flavours, gift message, '
        'service. Store pickups are excluded (see get_pickup_orders).',
        {
            'type': 'object',
            'properties': {
                'date': _DATE,
                'include_overdue': {'type': 'boolean', 'default': True},
                'include_undated': {'type': 'boolean', 'default': True},
            },
            'additionalProperties': False,
        },
    ),
    'get_upcoming_shipments': (
        get_upcoming_shipments,
        'Day-by-day calendar of orders still to post: per day the number of orders, '
        'boxes per product, shipping services and order ids.',
        {
            'type': 'object',
            'properties': {
                'date_from': {**_DATE, 'description': 'First day (default today).'},
                'days': {'type': 'integer', 'minimum': 1, 'maximum': 60, 'default': 7},
            },
            'additionalProperties': False,
        },
    ),
    'get_pickup_orders': (
        get_pickup_orders,
        'Orders to be collected in store between two dates (default today), with pickup time and contents.',
        {
            'type': 'object',
            'properties': {
                'date_from': _DATE,
                'date_to': _DATE,
                'include_collected': {'type': 'boolean', 'default': False},
            },
            'additionalProperties': False,
        },
    ),
    'get_production_totals': (
        get_production_totals,
        'What to make: totals per product (boxes, chocolates), per flavour '
        '(chocolates), random chocolates, pack extras (hot chocolate, gift cards, '
        'bark) and allergen exclusions, for a list of order ids or a shipping/created '
        'date range. By default only orders not yet shipped count.',
        {
            'type': 'object',
            'properties': {
                'order_ids': {'type': 'array', 'items': {'type': 'string'}},
                'shipping_date_from': _DATE,
                'shipping_date_to': _DATE,
                'created_from': _DATE,
                'created_to': _DATE,
                'only_open': {
                    'type': 'boolean', 'default': True,
                    'description': 'Ignored when order_ids is given.',
                },
            },
            'additionalProperties': False,
        },
    ),
    'get_sales_summary': (
        get_sales_summary,
        'Sales for a period of order dates (default last 30 days): paid orders, '
        'revenue, average order, chocolates sold, by status, by shipping service, '
        'discount codes, products, and a day/week/month series.',
        {
            'type': 'object',
            'properties': {
                'created_from': _DATE,
                'created_to': _DATE,
                'group_by': {'type': 'string', 'enum': ['day', 'week', 'month'], 'default': 'day'},
            },
            'additionalProperties': False,
        },
    ),
    'list_shipping_options': (
        list_shipping_options,
        'Shipping services offered at checkout: carrier, price, delivery days, guaranteed or not, service code.',
        {
            'type': 'object',
            'properties': {'include_inactive': {'type': 'boolean', 'default': False}},
            'additionalProperties': False,
        },
    ),
    'list_products': (
        list_products,
        'The product catalogue with what affects shipping: units per box, weight, '
        'sold out, preorder, fixed posting date, pickup only.',
        {
            'type': 'object',
            'properties': {'include_inactive': {'type': 'boolean', 'default': False}},
            'additionalProperties': False,
        },
    ),
}
