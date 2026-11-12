"""BUG-05: the personalised-chocolates form posted to an endpoint that did not
exist, and the error was only logged in the browser, so every request was
lost. These tests are the rule now: a request is stored, the team hears
about it, and a broken email cannot lose it."""
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from flavours.models import Flavour, FlavourCategory

from .models import ChocolateTemplate, PersonalisedRequest

URL = '/api/personalized/send-request/'


@override_settings(STAFF_EMAILS=['staff@example.com'])
class PersonalisedRequestTest(TestCase):
    def setUp(self):
        cache.clear()  # the throttle counts per IP across tests
        # Like the storefront: no login, CSRF enforced.
        self.client = APIClient(enforce_csrf_checks=True)
        self.template = ChocolateTemplate.objects.create(title='Heart')
        category = FlavourCategory.objects.create(name='Classics', slug='classics')
        self.caramel = Flavour.objects.create(
            name='Salted Caramel', slug='salted-caramel', description='x', mini_description='x', category=category)

    def payload(self, **overrides):
        data = {
            'template_slug': self.template.slug,
            'email': 'ada@example.com',
            'comments': 'For a wedding, gold if possible',
            'custom_design_names': ['Gold', 'White'],
            'flavours': [self.caramel.id],
            'quantity': 120,
        }
        data.update(overrides)
        return data

    def test_a_request_is_stored_and_the_team_is_told(self):
        response = self.client.post(URL, self.payload(), format='json')

        self.assertEqual(response.status_code, 201)
        saved = PersonalisedRequest.objects.get()
        self.assertEqual(saved.template, self.template)
        self.assertEqual(saved.email, 'ada@example.com')
        self.assertEqual(saved.design, ['Gold', 'White'])
        self.assertEqual(saved.flavours, ['Salted Caramel'])
        self.assertEqual(saved.quantity, 120)
        self.assertFalse(saved.handled)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['staff@example.com'])
        self.assertIn('ada@example.com', mail.outbox[0].subject)
        for detail in ('Heart', '120', 'Gold, White', 'Salted Caramel', 'For a wedding'):
            self.assertIn(detail, mail.outbox[0].body)

    def test_a_failing_email_loses_nothing(self):
        with mock.patch('personalized.views.send_mail', side_effect=OSError('SMTP down')):
            response = self.client.post(URL, self.payload(), format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(PersonalisedRequest.objects.count(), 1)

    def test_unknown_flavour_ids_are_dropped(self):
        self.client.post(URL, self.payload(flavours=[self.caramel.id, 99999]), format='json')
        self.assertEqual(PersonalisedRequest.objects.get().flavours, ['Salted Caramel'])

    def test_bad_requests_are_refused_and_nothing_is_stored(self):
        for field, value in (
            ('email', 'not-an-email'),
            ('email', ''),
            ('quantity', 0),
            ('template_slug', 'no-such-template'),
        ):
            with self.subTest(field=field, value=value):
                response = self.client.post(URL, self.payload(**{field: value}), format='json')
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
        self.assertFalse(PersonalisedRequest.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_someone_flooding_the_form_is_slowed_down(self):
        for _ in range(10):
            self.client.post(URL, self.payload(), format='json')
        response = self.client.post(URL, self.payload(), format='json')
        self.assertEqual(response.status_code, 429)
        self.assertEqual(PersonalisedRequest.objects.count(), 10)
