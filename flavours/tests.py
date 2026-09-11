"""Tests for the ``sync_flavours`` management command.

The command makes the set of active flavours match the current printed card:
it deactivates flavours that are no longer on the card, (re)activates the ones
that are, and creates the new ones. It must never delete flavours, because
cart selections point at them with on_delete=CASCADE.
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from allergens.models import Allergen
from flavours.management.commands.sync_flavours import CARD_FLAVOURS
from flavours.models import Flavour, FlavourCategory


class SyncFlavoursCommandTest(TestCase):
    # Names the card expects to already exist (no 'defaults' block) vs. new ones.
    EXISTING_NAMES = [f["name"] for f in CARD_FLAVOURS if "defaults" not in f]
    NEW_NAMES = [f["name"] for f in CARD_FLAVOURS if "defaults" in f]

    def setUp(self):
        self.category = FlavourCategory.objects.create(
            name="Originals", slug="originals", active=True
        )
        for slug in ["milk", "soy", "nuts", "gluten", "alcohol"]:
            Allergen.objects.create(name=slug.title(), slug=slug)

        # Seed every pre-existing card flavour, as production does (from the
        # initial_flavours fixture). One of them starts inactive to exercise the
        # reactivate path; the rest start active.
        self.on_card_inactive = self._flavour(self.EXISTING_NAMES[0], active=False)
        for name in self.EXISTING_NAMES[1:]:
            self._flavour(name, active=True)

        # A flavour not on the card -> gets deactivated (not deleted).
        self.off_card = self._flavour("Eggnog", active=True)

    def _flavour(self, name, active):
        return Flavour.objects.create(
            name=name,
            slug=name.lower().replace(" ", "-"),
            description="x",
            mini_description="x",
            category=self.category,
            active=active,
        )

    def _run(self, **kwargs):
        call_command("sync_flavours", stdout=StringIO(), **kwargs)

    def test_active_set_matches_card_after_sync(self):
        self._run()
        active = set(Flavour.objects.active().values_list("name", flat=True))
        self.assertEqual(active, {f["name"] for f in CARD_FLAVOURS})

    def test_off_card_flavour_deactivated_not_deleted(self):
        self._run()
        self.off_card.refresh_from_db()
        self.assertFalse(self.off_card.active)
        self.assertTrue(Flavour.objects.filter(pk=self.off_card.pk).exists())

    def test_inactive_card_flavour_reactivated(self):
        self._run()
        self.on_card_inactive.refresh_from_db()
        self.assertTrue(self.on_card_inactive.active)

    def test_new_card_flavours_created_with_allergens(self):
        self._run()
        dubai = Flavour.objects.get(name="Dubai Style")
        self.assertTrue(dubai.active)
        self.assertEqual(dubai.slug, "dubai-style")
        self.assertEqual(
            set(dubai.allergens.values_list("slug", flat=True)),
            {"milk", "soy", "nuts", "gluten"},
        )

    def test_dry_run_changes_nothing(self):
        before = set(Flavour.objects.active().values_list("name", flat=True))
        before_total = Flavour.objects.count()
        self._run(dry_run=True)
        after = set(Flavour.objects.active().values_list("name", flat=True))
        self.assertEqual(before, after)
        self.assertEqual(before_total, Flavour.objects.count())

    def test_idempotent(self):
        self._run()
        first = set(Flavour.objects.active().values_list("name", flat=True))
        first_total = Flavour.objects.count()
        self._run()
        self.assertEqual(first, set(Flavour.objects.active().values_list("name", flat=True)))
        self.assertEqual(first_total, Flavour.objects.count())
