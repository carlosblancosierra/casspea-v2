from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from .models import Lead

class LeadTests(APITestCase):
    def test_subscribe_newsletter(self):
        url = reverse('leads:subscribe')
        data = {'email': 'user@example.com'}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Lead.objects.count(), 1)
        self.assertEqual(Lead.objects.get().email, 'user@example.com')
        self.assertEqual(Lead.objects.get().lead_type, Lead.NEWSLETTER)
