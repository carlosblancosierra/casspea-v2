"""BUG-08: the unsubscribe link in our emails led to a page that did not
exist, and nothing ever recorded an opt-out. These tests are the rule now:
every email links to a working, personal unsubscribe link, and an address
that used it gets no more marketing email."""
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core import mail, signing
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from carts.models import Cart
from checkout.models import CheckoutSession
from mails.services import PendingCheckoutSessionsMailProcessor, ReviewRequestMailProcessor
from orders.models import Order

from .models import EmailOptOut, Lead
from .unsubscribe import email_from_token, opt_out, unsubscribe_token, unsubscribe_url

URL = '/api/leads/unsubscribe/'


class TokenTest(TestCase):
    def test_a_token_names_its_address_whatever_the_case(self):
        self.assertEqual(email_from_token(unsubscribe_token('  Ada@Example.COM ')), 'ada@example.com')

    def test_a_tampered_token_is_refused(self):
        token = unsubscribe_token('ada@example.com')
        with self.assertRaises(signing.BadSignature):
            email_from_token(token[:-2] + 'xx')

    def test_the_link_goes_to_the_storefront_page(self):
        self.assertTrue(unsubscribe_url('ada@example.com').startswith(f'{settings.SITE_URL}/unsubscribe?token='))


class EndpointTest(TestCase):
    def setUp(self):
        # Like a browser on the storefront: no login, CSRF enforced.
        self.client = APIClient(enforce_csrf_checks=True)

    def test_a_valid_link_opts_the_address_out(self):
        Lead.objects.create(email='Ada@Example.com')
        response = self.client.post(URL, {'token': unsubscribe_token('ada@example.com')}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'email': 'a•••@example.com'})
        self.assertTrue(EmailOptOut.objects.filter(email='ada@example.com').exists())
        self.assertTrue(Lead.objects.get().unsubscribed)

    def test_using_the_same_link_twice_is_fine(self):
        token = unsubscribe_token('ada@example.com')
        self.client.post(URL, {'token': token}, format='json')
        response = self.client.post(URL, {'token': token}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(EmailOptOut.objects.count(), 1)

    def test_a_bad_link_is_refused_and_records_nothing(self):
        for token in ('', 'nonsense', signing.dumps('ada@example.com', salt='another.salt')):
            with self.subTest(token=token):
                response = self.client.post(URL, {'token': token}, format='json')
                self.assertEqual(response.status_code, 400)
        self.assertFalse(EmailOptOut.objects.exists())


class EmailsCarryAWorkingLinkTest(TestCase):
    def test_no_template_links_to_the_old_dead_page(self):
        for template in Path(settings.BASE_DIR).glob('*/templates/**/*.html'):
            with self.subTest(template=str(template.relative_to(settings.BASE_DIR))):
                self.assertNotIn('casspea.co.uk/unsubscribe/"', template.read_text())

    def test_the_newsletter_welcome_email_carries_the_subscribers_own_link(self):
        APIClient().post('/api/leads/subscribe/', {'email': 'ada@example.com'}, format='json')
        self.assertEqual(len(mail.outbox), 1)
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn(unsubscribe_url('ada@example.com').replace('&', '&amp;'), html)

    def test_the_abandoned_cart_reminder_carries_the_customers_own_link(self):
        session = CheckoutSession.objects.create(cart=Cart.objects.create(session_id='s1'), email='ada@example.com')
        processor = PendingCheckoutSessionsMailProcessor()
        _, email_type = processor.get_pending_checkout_sessions()
        email = processor.build_email(session, email_type)
        self.assertIn(unsubscribe_url('ada@example.com'), email.body)


class OptedOutAddressesGetNoMarketingTest(TestCase):
    def make_session(self, email, session_id, payment_status=CheckoutSession.Status.PENDING):
        return CheckoutSession.objects.create(
            cart=Cart.objects.create(session_id=session_id), email=email, payment_status=payment_status,
        )

    def test_no_abandoned_cart_reminder_after_opting_out(self):
        self.make_session('Ada@Example.com', 'ada')
        self.make_session('grace@example.com', 'grace')
        opt_out('ada@example.com')
        sessions, _ = PendingCheckoutSessionsMailProcessor().get_pending_checkout_sessions()
        self.assertEqual([s.email for s in sessions], ['grace@example.com'])

    def test_no_review_request_after_opting_out(self):
        ten_days_ago = timezone.now() - timedelta(days=10)
        for email in ('ada@example.com', 'grace@example.com'):
            session = self.make_session(email, email, CheckoutSession.Status.PAID)
            Order.objects.create(checkout_session=session)
        Order.objects.update(created=ten_days_ago)
        opt_out('ADA@example.com')
        orders, _ = ReviewRequestMailProcessor().get_eligible_orders()
        self.assertEqual([order.email for order in orders], ['grace@example.com'])
