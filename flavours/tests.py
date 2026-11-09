from datetime import timedelta

from django.utils import timezone

from carts.tests.test_base import BaseAPITest
from flavours.models import Flavour, FlavourCategory


class ComingSoonFlavourTest(BaseAPITest):
    """A category with a launch date ahead (e.g. Christmas on 1 December) is
    shown off but cannot be picked into a box until that day."""

    def setUp(self):
        super().setUp()
        self.christmas = FlavourCategory.objects.create(
            name='Christmas', slug='christmas', featured=True,
            available_from=timezone.localdate() + timedelta(days=10),
        )
        self.gingerbread = Flavour.objects.create(
            name='Mulled Wine', slug='test-mulled-wine', description='Spiced.',
            mini_description='Spiced.', category=self.christmas,
        )

    def ids(self, response):
        return {f['id'] for f in response.data}

    def test_list_leaves_coming_soon_out_by_default(self):
        response = self.client.get('/api/flavours/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.gingerbread.id, self.ids(response))
        self.assertIn(1, self.ids(response))

    def test_list_includes_coming_soon_when_asked(self):
        response = self.client.get('/api/flavours/?include=coming_soon')
        flavour = next(f for f in response.data if f['id'] == self.gingerbread.id)
        self.assertTrue(flavour['coming_soon'])
        self.assertEqual(flavour['available_from'], self.christmas.available_from.isoformat())
        self.assertTrue(flavour['category']['featured'])
        other = next(f for f in response.data if f['id'] == 1)
        self.assertFalse(other['coming_soon'])

    def test_launch_day_makes_them_ordinary_flavours(self):
        self.christmas.available_from = timezone.localdate()
        self.christmas.save()
        response = self.client.get('/api/flavours/')
        self.assertIn(self.gingerbread.id, self.ids(response))

    def box(self, flavour_id):
        return {
            "product": 4,  # 9-piece box
            "quantity": 1,
            "box_customization": {
                "selection_type": "PICK_AND_MIX",
                "flavor_selections": [{"flavor": flavour_id, "quantity": 9}],
            },
        }

    def test_cannot_pick_a_coming_soon_flavour(self):
        response = self.client.post('/api/carts/items/', self.box(self.gingerbread.id), format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('coming soon', str(response.data['flavor_selections']))

    def test_can_pick_it_from_launch_day(self):
        self.christmas.available_from = timezone.localdate()
        self.christmas.save()
        response = self.client.post('/api/carts/items/', self.box(self.gingerbread.id), format='json')
        self.assertEqual(response.status_code, 201)
