from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APITestCase

from .models import EmailOptOut, Lead
from .unsubscribe import is_opted_out, opt_out


class NewsletterConsentTests(APITestCase):
    def subscribe(self, email):
        return self.client.post(reverse('leads:subscribe'), {'email': email}, format='json')

    def test_a_new_lead_after_an_unsubscribe_stays_opted_out(self):
        opt_out('ada@example.com')
        self.client.post(reverse('leads:generic-lead-subscribe'),
                         {'email': 'Ada@Example.com', 'lead_type': 'giveaway'}, format='json')

        self.assertTrue(Lead.objects.get(lead_type='giveaway').unsubscribed)

    def test_the_form_cannot_set_unsubscribed(self):
        opt_out('ada@example.com')
        self.client.post(reverse('leads:generic-lead-subscribe'),
                         {'email': 'ada@example.com', 'unsubscribed': False}, format='json')

        self.assertTrue(Lead.objects.get().unsubscribed)

    def test_signing_up_again_overrides_an_earlier_unsubscribe(self):
        self.subscribe('ada@example.com')
        opt_out('ada@example.com')

        self.subscribe('ADA@example.com')

        self.assertFalse(is_opted_out('ada@example.com'))
        self.assertFalse(Lead.objects.get(lead_type=Lead.NEWSLETTER).unsubscribed)

    def test_signing_up_twice_keeps_one_lead(self):
        self.subscribe('ada@example.com')
        self.subscribe('Ada@example.com')

        self.assertEqual(Lead.objects.filter(lead_type=Lead.NEWSLETTER).count(), 1)

    def test_a_mail_failure_still_subscribes_and_hides_the_error(self):
        with patch('leads.views.send_mail', side_effect=Exception('SMTP auth failed for user x')):
            response = self.subscribe('ada@example.com')

        self.assertEqual(response.status_code, 201)
        self.assertNotIn('SMTP', str(response.data))
        self.assertEqual(Lead.objects.count(), 1)
