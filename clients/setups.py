"""Client pages that can be loaded from the admin panel in one click.

Each setup describes a client page and its products. Loading it (see
loader.py) creates or updates everything in the database, so nobody has to
type products into the Django admin. Stripe prices are created by hand first;
their ids go here.

To add a client: create the Stripe prices, add an entry below, deploy, then
press "Load" in the front-end admin (/admin/client-setups). Loading again
updates the rows in place and keeps the access code.
"""
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class SetupProduct:
    slug: str
    name: str
    price: Decimal
    stripe_price_id: str
    units_per_box: int
    quantity_step: int = 1
    # Copy weight, colours, description and pictures from this shop product.
    source_slug: str = ''
    # Optional flavour (by name) whose picture/description the page can use.
    flavour_name: str = ''


@dataclass(frozen=True)
class ClientSetup:
    slug: str
    name: str
    welcome_message: str
    brand_color: str = ''
    products: list = field(default_factory=list)


SETUPS = {
    'wild-at-heart': ClientSetup(
        slug='wild-at-heart',
        name='Wild at Heart',
        welcome_message=(
            "Welcome! Choose how many boxes you'd like and add them to your cart. "
            "Every box is filled with a selection of our handmade chocolates."
        ),
        products=[
            SetupProduct(
                slug='wild-at-heart-box-9', name='Wild at Heart - Box of 9',
                price=Decimal('13.00'), stripe_price_id='price_1UaJ4LJiuFqKKcn6xRPbMmta',
                units_per_box=9, source_slug='9-bonbons',
            ),
            SetupProduct(
                slug='wild-at-heart-box-15', name='Wild at Heart - Box of 15',
                price=Decimal('21.00'), stripe_price_id='price_1UadXaJiuFqKKcn6R8zUdtUC',
                units_per_box=15, source_slug='15-bonbons',
            ),
            SetupProduct(
                slug='wild-at-heart-box-24', name='Wild at Heart - Box of 24',
                price=Decimal('30.00'), stripe_price_id='price_1UadcdJiuFqKKcn6vXBdQ6cz',
                units_per_box=24, source_slug='24-bonbons',
            ),
        ],
    ),
}
