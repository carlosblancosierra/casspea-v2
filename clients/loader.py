"""Load a client setup (setups.py) into the database."""
import secrets

from django.db import transaction

from flavours.models import Flavour
from products.models import Product, ProductCategory

from .models import ClientPage, ClientPageItem

CATEGORY_SLUG = 'client-chocolates'
CATEGORY_NAME = 'Client Chocolates'

# No 0/O or 1/I/L, so a code survives being read out over the phone.
CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'

IMAGE_FIELDS = ('image', 'image_webp', 'thumbnail', 'thumbnail_webp')


def make_code(prefix):
    groups = [''.join(secrets.choice(CODE_ALPHABET) for _ in range(4)) for _ in range(2)]
    return f"{prefix}-{'-'.join(groups)}"


def code_prefix(name):
    letters = ''.join(word[0] for word in name.split() if word[0].isalnum()).upper()
    return (letters or 'CLIENT')[:4]


class _DryRun(Exception):
    pass


def setup_status(setup):
    """What already exists in the database for this setup."""
    page = ClientPage.objects.filter(slug=setup.slug).first()
    products = []
    for spec in setup.products:
        product = Product.objects.filter(slug=spec.slug).first()
        products.append({
            'slug': spec.slug,
            'name': spec.name,
            'price': str(spec.price),
            'stripe_price_id': spec.stripe_price_id,
            'exists': bool(product),
            'up_to_date': bool(product) and product.base_price == spec.price
            and product.stripe_price_id == spec.stripe_price_id,
        })
    return {
        'key': setup.slug,
        'name': setup.name,
        'path': f'/clients/{setup.slug}',
        'page_exists': bool(page),
        'page_active': bool(page and page.active),
        'has_access_code': bool(page and page.has_access_code),
        'products': products,
    }


def load_setup(setup, *, dry_run=False, new_code=False):
    """Create or update the page, its products and links.

    Returns {'log': [...], 'access_code': str|None}. The access code is only
    returned when it is set by this call (new page, or new_code=True): it is
    stored hashed and can't be shown again.
    """
    log = []
    result = {'log': log, 'access_code': None, 'dry_run': dry_run}
    try:
        with transaction.atomic():
            _load(setup, new_code, log, result)
            if dry_run:
                raise _DryRun
    except _DryRun:
        log.append('Dry run: nothing was saved.')
        result['access_code'] = None
    return result


def _load(setup, new_code, log, result):
    category, created = ProductCategory.objects.get_or_create(
        slug=CATEGORY_SLUG,
        defaults={
            'name': CATEGORY_NAME,
            'description': 'Products made for a single client. Never shown in the shop.',
            'active': False,
        },
    )
    log.append(f"{'Created' if created else 'Found'} hidden category '{category.name}'.")

    page, created = ClientPage.objects.get_or_create(
        slug=setup.slug,
        defaults={
            'name': setup.name,
            'brand_color': setup.brand_color,
            'welcome_message': setup.welcome_message,
        },
    )
    log.append(f"{'Created' if created else 'Found'} client page /clients/{page.slug}.")
    if new_code or not page.has_access_code:
        code = make_code(code_prefix(setup.name))
        page.set_access_code(code)
        page.save(update_fields=['access_code_hash', 'updated'])
        result['access_code'] = code
        log.append('Set a new access code.')
    else:
        log.append('Access code unchanged.')

    for order, spec in enumerate(setup.products):
        source = Product.objects.filter(slug=spec.source_slug).first() if spec.source_slug else None
        if spec.source_slug and not source:
            log.append(f"  No shop product '{spec.source_slug}' to copy from: using defaults.")
        defaults = {
            'name': spec.name,
            'description': source.description if source else f'{spec.name}, made for {setup.name}.',
            'category': category,
            'base_price': spec.price,
            'stripe_price_id': spec.stripe_price_id,
            'weight': source.weight if source else 12 * spec.units_per_box,
            'box_weight': source.box_weight if source else 150,
            'units_per_box': spec.units_per_box,
            'main_color': source.main_color if source else '#000000',
            'secondary_color': source.secondary_color if source else '#FFFFFF',
            'seo_title': spec.name,
            'seo_description': spec.name,
            'active': True,
            'client_only': True,
            'quantity_step': spec.quantity_step,
            'disable_flavour_selection': True,
            'can_pick_allergens': source.can_pick_allergens if source else False,
        }
        product, created = Product.objects.update_or_create(slug=spec.slug, defaults=defaults)
        if source and source.image:
            # Point at the shop product's pictures (same files) instead of
            # copying them. Product.delete keeps files another product uses.
            Product.objects.filter(pk=product.pk).update(
                **{f: getattr(source, f).name or '' for f in IMAGE_FIELDS}
            )
        flavour = (
            Flavour.objects.filter(name__iexact=spec.flavour_name).first()
            if spec.flavour_name else None
        )
        ClientPageItem.objects.update_or_create(
            page=page, product=product, defaults={'flavour': flavour, 'order': order},
        )
        log.append(f"  {'Created' if created else 'Updated'} {spec.name} (£{spec.price}, {spec.stripe_price_id}).")
