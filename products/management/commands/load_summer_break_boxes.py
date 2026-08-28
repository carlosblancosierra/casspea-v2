"""Create (or tear down) the Summer Break clearance boxes.

These are clones of the four Signature Boxes (9 / 15 / 24 / 48) with a 25% price
cut already baked into the price. They are "Surprise Me" only (no flavour
picking) and no discount code can stack on top of them.

Typical usage
-------------
Preview everything without touching the DB or Stripe::

    python manage.py load_summer_break_boxes --dry-run

Create the category, the Stripe prices and the four products (category stays
hidden from the shop grid — reachable only via /landing/summer-break)::

    python manage.py load_summer_break_boxes

Same, but also make the category visible in the shop when you're ready::

    python manage.py load_summer_break_boxes --publish

Reuse Stripe prices you created by hand (skip the Stripe API)::

    python manage.py load_summer_break_boxes --no-stripe \
        --price-id 9=price_x --price-id 15=price_y \
        --price-id 24=price_z --price-id 48=price_w

Pull the boxes after the sale (hide them from the shop)::

    python manage.py load_summer_break_boxes --deactivate

The command is idempotent: running it again updates the existing rows in place
and reuses Stripe prices (matched by ``lookup_key``) rather than duplicating.
"""
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from products.models import Product, ProductCategory


CATEGORY_NAME = "Summer Break Boxes"
CATEGORY_SLUG = "summer-break-boxes"
CATEGORY_DESCRIPTION = (
    "Our kitchen clear-out before the summer break — the same handmade boxes at "
    "25% off. Pick your allergens and let us surprise you with the flavours."
)

# units_per_box -> source Signature Box to clone from (by slug, or by pk when the
# slug doesn't follow the pattern — e.g. the 96 box).
SOURCE_BY_UNITS = {
    9: {"slug": "9-bonbons"},
    15: {"slug": "15-bonbons"},
    24: {"slug": "24-bonbons"},
    48: {"slug": "48-bonbons"},
    96: {"id": 401},
}


def _get_source_product(units, ref):
    from products.models import Product as _Product
    if "id" in ref:
        return _Product.objects.get(pk=ref["id"])
    return _Product.objects.get(slug=ref["slug"])


class Command(BaseCommand):
    help = "Create/refresh (or deactivate) the Summer Break 25%-off clearance boxes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--discount-percent", type=int, default=25,
            help="Percentage taken off the source box price (default: 25).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Print what would happen without writing to the DB or Stripe.",
        )
        parser.add_argument(
            "--no-stripe", action="store_true",
            help="Do not touch the Stripe API. Supply price IDs with --price-id.",
        )
        parser.add_argument(
            "--price-id", action="append", default=[], metavar="UNITS=price_xxx",
            help="Pre-created Stripe price id for a box size, e.g. --price-id 9=price_abc. "
                 "Repeat per size. Overrides Stripe creation for that size.",
        )
        parser.add_argument(
            "--publish", action="store_true",
            help="Make the category visible in the shop grid. Off by default so the "
                 "boxes are only reachable via the /landing/summer-break link while testing.",
        )
        parser.add_argument(
            "--deactivate", action="store_true",
            help="Hide the Summer Break boxes (active=False, sold_out=True) instead of creating them.",
        )

    # ---- helpers -----------------------------------------------------------

    def _parse_price_overrides(self, raw_list):
        overrides = {}
        for entry in raw_list:
            if "=" not in entry:
                raise CommandError(f"--price-id must look like UNITS=price_xxx, got '{entry}'")
            units_str, price_id = entry.split("=", 1)
            try:
                overrides[int(units_str)] = price_id.strip()
            except ValueError:
                raise CommandError(f"Invalid units in --price-id '{entry}'")
        return overrides

    def _discounted_price(self, base_price, percent):
        factor = (Decimal(100) - Decimal(percent)) / Decimal(100)
        return (Decimal(base_price) * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _get_or_create_stripe_price(self, source, units, amount, dry_run):
        """Return a Stripe price id for the given box, creating it if needed."""
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY

        lookup_key = f"summer_break_{units}"
        amount_pence = int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))

        if dry_run:
            self.stdout.write(
                f"    [dry-run] would ensure Stripe price lookup_key={lookup_key} "
                f"amount={amount_pence}p (gbp)"
            )
            return f"<dry-run:{lookup_key}>"

        existing = stripe.Price.list(lookup_keys=[lookup_key], limit=1).data
        if existing:
            self.stdout.write(f"    reusing Stripe price {existing[0].id} ({lookup_key})")
            return existing[0].id

        product = stripe.Product.create(
            name=f"Summer Break Box of {units} Hand Made Chocolates",
            metadata={"summer_break": "true", "units_per_box": str(units)},
        )
        price = stripe.Price.create(
            product=product.id,
            unit_amount=amount_pence,
            currency="gbp",
            lookup_key=lookup_key,
            metadata={"summer_break": "true", "units_per_box": str(units)},
        )
        self.stdout.write(f"    created Stripe price {price.id} ({lookup_key})")
        return price.id

    # ---- main --------------------------------------------------------------

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        percent = options["discount_percent"]
        no_stripe = options["no_stripe"]
        deactivate = options["deactivate"]
        publish = options["publish"]
        overrides = self._parse_price_overrides(options["price_id"])

        if deactivate:
            return self._handle_deactivate(dry_run)

        # 1. Category — hidden from the shop grid unless --publish is passed, so the
        # boxes can be tested privately via /landing/summer-break first.
        category_visibility = "visible in shop" if publish else "hidden (link-only)"
        if dry_run:
            self.stdout.write(
                f"[dry-run] would ensure category '{CATEGORY_NAME}' ({CATEGORY_SLUG}) — {category_visibility}"
            )
            category = None
        else:
            category, created = ProductCategory.objects.update_or_create(
                slug=CATEGORY_SLUG,
                defaults={
                    "name": CATEGORY_NAME,
                    "description": CATEGORY_DESCRIPTION,
                    "active": publish,
                    "order": 0,
                },
            )
            self.stdout.write(self.style.SUCCESS(
                f"{'Created' if created else 'Updated'} category {category.name} ({category_visibility})"
            ))

        # 2. Boxes
        for units, source_ref in SOURCE_BY_UNITS.items():
            try:
                source = _get_source_product(units, source_ref)
            except Product.DoesNotExist:
                raise CommandError(
                    f"Source box for {units} units not found ({source_ref}) — load the Signature Boxes first."
                )

            amount = self._discounted_price(source.base_price, percent)
            new_slug = f"summer-break-{units}-bonbons"
            self.stdout.write(
                f"\nBox of {units}: £{source.base_price} -> £{amount} ({percent}% off) [{new_slug}]"
            )

            # Resolve Stripe price id
            if units in overrides:
                price_id = overrides[units]
                self.stdout.write(f"    using supplied Stripe price {price_id}")
            elif no_stripe:
                raise CommandError(
                    f"--no-stripe set but no --price-id for units={units}. "
                    f"Provide --price-id {units}=price_xxx."
                )
            else:
                price_id = self._get_or_create_stripe_price(source, units, amount, dry_run)

            if dry_run:
                self.stdout.write(
                    f"    [dry-run] would create/update product '{new_slug}' "
                    f"(category={CATEGORY_SLUG}, price_id={price_id}, surprise-only, no-stacking)"
                )
                continue

            with transaction.atomic():
                product, created = Product.objects.update_or_create(
                    slug=new_slug,
                    defaults={
                        "name": f"Summer Break Box of {units} Hand Made Chocolates",
                        "description": source.description,
                        "category": category,
                        "base_price": amount,
                        "compare_at_price": source.base_price,
                        "stripe_price_id": price_id,
                        "weight": source.weight,
                        "box_weight": source.box_weight,
                        "units_per_box": units,
                        "active": True,
                        "sold_out": False,
                        "main_color": source.main_color,
                        "secondary_color": source.secondary_color,
                        "seo_title": f"Summer Break Box of {units} – 25% Off Handmade Chocolates",
                        "seo_description": (
                            f"Clear-out offer: {units} handmade CassPea chocolates at {percent}% off. "
                            "Surprise Me selection, pick your allergens."
                        ),
                        "can_pick_allergens": True,
                        "disable_flavour_selection": True,
                        "block_discount_codes": True,
                    },
                )
                # Reuse the source images (same S3 keys) without re-processing them.
                Product.objects.filter(pk=product.pk).update(
                    image=source.image.name if source.image else "",
                    image_webp=source.image_webp.name if source.image_webp else "",
                    thumbnail=source.thumbnail.name if source.thumbnail else "",
                    thumbnail_webp=source.thumbnail_webp.name if source.thumbnail_webp else "",
                )
            self.stdout.write(self.style.SUCCESS(
                f"    {'Created' if created else 'Updated'} product {product.name}"
            ))

        self.stdout.write(self.style.SUCCESS("\nDone." + (" (dry-run)" if dry_run else "")))

    def _handle_deactivate(self, dry_run):
        slugs = [f"summer-break-{u}-bonbons" for u in SOURCE_BY_UNITS]
        qs = Product.objects.filter(slug__in=slugs)
        if dry_run:
            self.stdout.write(f"[dry-run] would deactivate {qs.count()} Summer Break boxes: {slugs}")
            return
        updated = qs.update(active=False, sold_out=True)
        self.stdout.write(self.style.SUCCESS(f"Deactivated {updated} Summer Break boxes."))
