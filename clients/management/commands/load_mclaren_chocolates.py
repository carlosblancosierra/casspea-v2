"""Create (or refresh) the McLaren client page and its individual chocolates.

The four products are client-only: hidden from the shop and the product API,
sold in multiples of 10, and only users allowed on the McLaren page can add
them to the cart. The Stripe prices were created by hand in the live account
(£1.80 per piece, VAT inclusive), so this command never calls Stripe.

Usage::

    python manage.py load_mclaren_chocolates --dry-run
    python manage.py load_mclaren_chocolates --allow @mclaren.com
    python manage.py load_mclaren_chocolates --allow anna@mclaren.com --allow ops@mclaren.com

``--allow`` replaces the page's allowed list; leave it out to keep the current
one (a new page starts empty, which means staff only). Running the command
again updates the rows in place instead of duplicating them.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from clients.models import ClientPage, ClientPageItem
from flavours.models import Flavour
from products.models import Product, ProductCategory

PAGE_SLUG = 'mclaren'
PAGE_NAME = 'McLaren'
BRAND_COLOR = '#FF8000'
WELCOME = (
    "Welcome! Choose your favourite flavours and how many of each you'd like, "
    "then add them to your cart."
)

CATEGORY_SLUG = 'client-chocolates'
CATEGORY_NAME = 'Client Chocolates'

UNIT_PRICE = Decimal('1.80')
QUANTITY_STEP = 10

# (flavour name, Stripe price id) — order is the order on the page.
CHOCOLATES = [
    ('Vanilla Pecan', 'price_1UZvuaJiuFqKKcn6VmKbat9y'),
    ('Cinnamon and Spice Caramel', 'price_1UZvujJiuFqKKcn6HqXIn9fR'),
    ('Sea Salt Caramel', 'price_1UZvulJiuFqKKcn6PTpdBwU0'),
    ('Dark Chocolate Ganache', 'price_1UZvumJiuFqKKcn6twHwglhc'),
]


def _slugify(name):
    return 'mclaren-' + '-'.join(name.lower().replace('&', 'and').split())


class Command(BaseCommand):
    help = "Create/refresh the McLaren client page and its four individual chocolates."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="Show what would happen without writing anything.")
        parser.add_argument('--allow', action='append', default=None, metavar='EMAIL_OR_@DOMAIN',
                            help="Who may use the page. Repeat for several. Replaces the current list.")

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        with transaction.atomic():
            self._run(opts['allow'])
            if dry:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("Dry run: nothing was saved."))

    def _run(self, allow):
        category, created = ProductCategory.objects.get_or_create(
            slug=CATEGORY_SLUG,
            defaults={
                'name': CATEGORY_NAME,
                'description': 'Products made for a single client. Never shown in the shop.',
                'active': False,
            },
        )
        self.stdout.write(f"{'Created' if created else 'Found'} hidden category '{category.name}'")

        page, created = ClientPage.objects.get_or_create(
            slug=PAGE_SLUG,
            defaults={'name': PAGE_NAME, 'brand_color': BRAND_COLOR, 'welcome_message': WELCOME},
        )
        if allow is not None:
            page.allowed_emails = '\n'.join(a.strip() for a in allow if a.strip())
            page.save(update_fields=['allowed_emails', 'updated'])
        self.stdout.write(f"{'Created' if created else 'Found'} client page '/clients/{page.slug}'")
        allowed = page.allowed_emails.split() or ['(staff only)']
        self.stdout.write(f"  allowed: {', '.join(allowed)}")

        for order, (flavour_name, price_id) in enumerate(CHOCOLATES):
            name = f"McLaren - Individual Chocolate - {flavour_name}"
            product, created = Product.objects.update_or_create(
                slug=_slugify(flavour_name),
                defaults={
                    'name': name,
                    'description': f"{flavour_name} individual chocolate, made for McLaren.",
                    'category': category,
                    'base_price': UNIT_PRICE,
                    'stripe_price_id': price_id,
                    'weight': 12,
                    'box_weight': 0,
                    'units_per_box': 1,
                    'main_color': BRAND_COLOR,
                    'secondary_color': '#FFFFFF',
                    'seo_title': name,
                    'seo_description': name,
                    'active': True,
                    'client_only': True,
                    'quantity_step': QUANTITY_STEP,
                    'disable_flavour_selection': True,
                },
            )
            flavour = Flavour.objects.filter(name__iexact=flavour_name).first()
            ClientPageItem.objects.update_or_create(
                page=page, product=product,
                defaults={'flavour': flavour, 'order': order},
            )
            note = '' if flavour else '  (no flavour with this name: no picture on the page)'
            self.stdout.write(
                f"{'Created' if created else 'Updated'} {name} -> {price_id}{note}"
            )
