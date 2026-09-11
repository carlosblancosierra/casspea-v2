"""Sync the live flavour catalogue to match the current printed flavour card.

This command makes the set of *active* flavours match a fixed list (``CARD_FLAVOURS``
below — the flavours printed on the current card / "op1"). It:

* deactivates every flavour whose name is NOT on the card (``active=False``),
* reactivates any card flavour that already exists but is inactive,
* creates the card flavours that don't exist yet (with description, mini
  description, allergens and category filled in).

Flavours are never deleted: ``carts.CartPackFlavorSelection.flavor`` points at
``Flavour`` with ``on_delete=CASCADE``, so deleting a flavour would wipe historical
cart data. Deactivating hides it from the shop (``FlavourListView`` uses
``Flavour.objects.active()``) while keeping referential integrity.

The command only ever touches the ``active`` flag of *existing* flavours — it
never overwrites their curated description / allergens / images. Full content is
only written when a card flavour has to be *created*.

Usage
-----
Preview the changes without writing anything::

    python manage.py sync_flavours --dry-run

Apply the changes::

    python manage.py sync_flavours

The command is idempotent — running it again is a no-op once the catalogue
matches the card. When the card changes, edit ``CARD_FLAVOURS`` and re-run.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from allergens.models import Allergen
from flavours.models import Flavour, FlavourCategory


# Allergen note from the card:
#   "All chocolates contain Milk Solids and Soy."  -> every flavour gets milk + soy
#   Brownie / Crunchy Peanut / Praline Feuilletine / Vanilla Pecan / Dubai Style
#       "Contains Nuts and Gluten" (Brownie: Gluten only).
BASE_ALLERGENS = ["milk", "soy"]

# The flavours printed on the current card, in card order.
#
# ``defaults`` is ONLY used when the flavour has to be created (it doesn't exist
# yet). Existing flavours keep their curated content and are just (re)activated.
# ``allergens`` are allergen slugs (see allergens/fixtures/initial_allergens.json:
# milk, gluten, soy, wheat, alcohol, nuts).
CARD_FLAVOURS = [
    # --- already in the catalogue: only need to stay/become active ---
    {"name": "Strawberry and Vanilla"},
    {"name": "Crunchy Peanut"},
    {"name": "Vanilla Pecan"},
    {"name": "Apple Pie"},
    {"name": "Brownie"},
    {"name": "Horchata"},
    {"name": "Whisky and Vanilla Caramel"},
    {"name": "Mango and Passionfruit Caramel"},
    {"name": "Praline Feuilletine"},
    {"name": "Cookie Dough"},
    {"name": "Banana Caramel"},
    {"name": "Milk Chocolate Ganache"},
    # --- new flavours to create ---
    {
        "name": "Sicilian Lemon Cheesecake",
        "defaults": {
            "description": (
                "A bright and zesty cheesecake flavour, bringing together tangy "
                "Sicilian lemon and a smooth, creamy ganache."
            ),
            "mini_description": "Tangy Sicilian lemon with a creamy cheesecake ganache.",
            "allergens": BASE_ALLERGENS,
        },
    },
    {
        "name": "Dubai Style",
        "defaults": {
            "description": (
                "Our take on the famous Dubai chocolate, with a rich pistachio "
                "cream and crispy kataifi for the perfect crunch."
            ),
            "mini_description": "Rich pistachio and crispy kataifi, inspired by the Dubai chocolate.",
            "allergens": BASE_ALLERGENS + ["nuts", "gluten"],
        },
    },
    {
        "name": "Salted Caramel",
        "defaults": {
            "description": (
                "A timeless favourite — smooth, buttery caramel finished with a "
                "delicate touch of sea salt."
            ),
            "mini_description": "Smooth buttery caramel with a touch of sea salt.",
            "allergens": BASE_ALLERGENS,
        },
    },
    {
        "name": "Cappuccino",
        "defaults": {
            "description": (
                "For our coffee lovers, a creamy cappuccino ganache with warm "
                "notes of espresso and milk."
            ),
            "mini_description": "A creamy cappuccino ganache with notes of espresso.",
            "allergens": BASE_ALLERGENS,
        },
    },
    {
        "name": "Mezcal Margarita",
        "defaults": {
            "description": (
                "A zesty cocktail-inspired flavour, with bright lime and a smoky "
                "hint of mezcal."
            ),
            "mini_description": "Bright lime and smoky mezcal in a margarita twist.",
            "allergens": BASE_ALLERGENS + ["alcohol"],
        },
    },
    {
        "name": "64% Colombian Dark Chocolate Ganache",
        "defaults": {
            "description": (
                "A rich and intense ganache made with single-origin 64% Colombian "
                "dark chocolate."
            ),
            "mini_description": "A rich ganache made with 64% Colombian dark chocolate.",
            "allergens": BASE_ALLERGENS,
        },
    },
]


def _norm(name):
    return " ".join(name.split()).lower()


class Command(BaseCommand):
    help = "Sync active flavours to match the current printed flavour card (op1)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        card_by_norm = {_norm(f["name"]): f for f in CARD_FLAVOURS}
        existing_by_norm = {_norm(f.name): f for f in Flavour.objects.all()}

        to_deactivate = []   # currently active, not on the card
        to_reactivate = []   # on the card, exists but inactive
        already_active = []  # on the card, exists and active
        to_create = []       # on the card, does not exist

        # Existing flavours: decide activate vs deactivate.
        for norm, flavour in existing_by_norm.items():
            on_card = norm in card_by_norm
            if on_card:
                (already_active if flavour.active else to_reactivate).append(flavour)
            elif flavour.active:
                to_deactivate.append(flavour)

        # Card flavours that have no matching existing row.
        for norm, spec in card_by_norm.items():
            if norm not in existing_by_norm:
                to_create.append(spec)

        # ---- report ----
        self.stdout.write(self.style.MIGRATE_HEADING("\nFlavour card sync plan"))
        self._list("Deactivate (not on the card)", [f.name for f in to_deactivate])
        self._list("Reactivate (on card, was inactive)", [f.name for f in to_reactivate])
        self._list("Create (new on the card)", [s["name"] for s in to_create])
        self._list("Already active (no change)", [f.name for f in already_active], style=None)

        if to_create and not all("defaults" in s for s in to_create):
            missing = [s["name"] for s in to_create if "defaults" not in s]
            self.stdout.write(self.style.ERROR(
                "\nAborting: these card flavours are expected to already exist "
                f"but were not found (matched by name): {missing}. They have no "
                "'defaults' block to create them from. Check the names match the "
                "existing flavours, or add a 'defaults' block in CARD_FLAVOURS."
            ))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING("\n[dry-run] No changes written."))
            return

        if not (to_deactivate or to_reactivate or to_create):
            self.stdout.write(self.style.SUCCESS("\nCatalogue already matches the card. Nothing to do."))
            return

        with transaction.atomic():
            for flavour in to_deactivate:
                flavour.active = False
                flavour.save(update_fields=["active", "updated"])

            for flavour in to_reactivate:
                flavour.active = True
                flavour.save(update_fields=["active", "updated"])

            category = self._default_category()
            for spec in to_create:
                self._create_flavour(spec, category)

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Deactivated {len(to_deactivate)}, reactivated {len(to_reactivate)}, "
            f"created {len(to_create)}. Active flavours now: {Flavour.objects.active().count()}."
        ))

    # ---- helpers ----------------------------------------------------------

    def _list(self, title, names, style="NOTICE"):
        header = f"\n{title} ({len(names)}):"
        self.stdout.write(getattr(self.style, style)(header) if style else header)
        for name in sorted(names):
            self.stdout.write(f"  - {name}")
        if not names:
            self.stdout.write("  (none)")

    def _default_category(self):
        category = (
            FlavourCategory.objects.filter(slug="originals").first()
            or FlavourCategory.objects.order_by("pk").first()
        )
        if category is None:
            category = FlavourCategory.objects.create(name="Originals", slug="originals", active=True)
            self.stdout.write(self.style.WARNING("  created missing category 'Originals'"))
        return category

    def _unique_slug(self, name):
        base = slugify(name)
        slug = base
        i = 2
        while Flavour.objects.filter(slug=slug).exists():
            slug = f"{base}-{i}"
            i += 1
        return slug

    def _create_flavour(self, spec, category):
        defaults = spec["defaults"]
        flavour = Flavour.objects.create(
            name=spec["name"],
            slug=self._unique_slug(spec["name"]),
            description=defaults["description"],
            mini_description=defaults["mini_description"],
            category=category,
            active=True,
        )

        allergen_slugs = defaults.get("allergens", [])
        allergens = list(Allergen.objects.filter(slug__in=allergen_slugs))
        found = {a.slug for a in allergens}
        missing = [s for s in allergen_slugs if s not in found]
        if missing:
            self.stdout.write(self.style.WARNING(
                f"  {spec['name']}: allergen slugs not found (skipped): {missing}"
            ))
        flavour.allergens.set(allergens)

        self.stdout.write(self.style.SUCCESS(
            f"  created {flavour.name} (allergens: {sorted(found)})"
        ))
