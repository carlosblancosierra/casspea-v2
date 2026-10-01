"""Tests for the SMS contact list.

The numbers are free text typed by customers at checkout, one Address row per
checkout attempt (up to two, shipping and billing, each time), so both the
parsing and the deduplication are load-bearing: without them the "how many
people can we text" number is wrong in both directions.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from carts.models import Cart
from checkout.models import CheckoutSession

from .models import Address
from .phones import normalise_uk_mobile, split_name
from .views import collect_sms_contacts

URL = '/api/addresses/sms-contacts/'


def make_address(phone, created=None, **kwargs):
    fields = {
        'address_type': Address.AddressType.SHIPPING_ADDRESS,
        'street_address': '1 Test Street',
        'city': 'London',
        'postcode': 'SW1A 1AA',
    }
    fields.update(kwargs)
    address = Address.objects.create(phone=phone, **fields)
    if created is not None:
        # created is auto_now_add, so it can only be backdated after the fact.
        Address.objects.filter(pk=address.pk).update(created=created)
        address.refresh_from_db()
    return address


def make_checkout(address, email=None, user=None, created=None):
    """Attach an email to an address the only way the data model allows.

    Address has no email column; the email a customer gave is on the checkout
    that used the address. A guest's sits in CheckoutSession.email, and a
    logged-in customer's is nulled there by CheckoutSession.save and lives on
    the cart's user instead.
    """
    cart = Cart.objects.create(user=user)
    session = CheckoutSession.objects.create(
        cart=cart,
        shipping_address=address,
        email=email,
    )
    if created is not None:
        CheckoutSession.objects.filter(pk=session.pk).update(created=created)
    return session


class NormaliseUkMobileTest(TestCase):
    def test_uk_mobiles_normalise_to_e164(self):
        for raw in [
            '07700 900123',
            '+44 7700 900123',
            '00447700900123',
            '447700900123',
            '7700900123',
            '(07700) 900-123',
            '  07700900123  ',
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(normalise_uk_mobile(raw), '+447700900123')

    def test_non_mobiles_are_rejected(self):
        for raw in [
            None,
            '',
            '   ',
            'not a number',
            '020 7946 0958',      # London landline
            '0121 496 0123',      # Birmingham landline
            '+33 6 12 34 56 78',  # French mobile
            '0770090012',         # one digit short
            '077009001234',       # one digit long
            '07024 900123',       # 070 personal numbering, not a mobile
            '07600 900123',       # 076 pager range
        ]:
            with self.subTest(raw=raw):
                self.assertIsNone(normalise_uk_mobile(raw))

    def test_isle_of_man_mobiles_are_kept(self):
        """07624 is the one textable range inside 076."""
        self.assertEqual(normalise_uk_mobile('07624 900123'), '+447624900123')

    def test_split_name_prefers_the_structured_pair(self):
        self.assertEqual(split_name('Ada', 'Lovelace', 'Ignored Name'), ('Ada', 'Lovelace'))

    def test_split_name_falls_back_to_full_name(self):
        self.assertEqual(split_name(None, None, 'Ada Lovelace'), ('Ada', 'Lovelace'))
        self.assertEqual(split_name('', '', 'Ada Byron King Lovelace'), ('Ada', 'Byron King Lovelace'))
        self.assertEqual(split_name('', '', 'Cher'), ('Cher', ''))
        self.assertEqual(split_name(None, None, None), ('', ''))


class CollectSmsContactsTest(TestCase):
    def test_rows_sharing_a_number_collapse_into_one_contact(self):
        """Shipping + billing on one checkout is two rows, one person."""
        make_address('07700 900123', first_name='Ada', last_name='Lovelace')
        make_address(
            '+44 7700 900123',
            address_type=Address.AddressType.BILLING_ADDRESS,
            first_name='Ada',
            last_name='Lovelace',
        )

        contacts = collect_sms_contacts()

        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]['phone'], '+447700900123')

    def test_landlines_and_blanks_are_left_out(self):
        make_address('07700 900123')
        make_address('020 7946 0958')
        make_address('')
        make_address(None)

        contacts = collect_sms_contacts()

        self.assertEqual([c['phone'] for c in contacts], ['+447700900123'])

    def test_first_seen_is_the_oldest_row_and_the_name_is_the_newest(self):
        now = timezone.now()
        make_address(
            '07700 900123',
            created=now - timedelta(days=60),
            first_name='Ada',
            last_name='Byron',
        )
        make_address(
            '07700 900123',
            created=now - timedelta(days=1),
            first_name='Ada',
            last_name='Lovelace',
        )

        contact = collect_sms_contacts()[0]

        self.assertEqual(contact['last_name'], 'Lovelace')
        self.assertLess(contact['first_seen'], now - timedelta(days=59))

    def test_a_later_blank_name_does_not_erase_the_one_we_have(self):
        now = timezone.now()
        make_address('07700 900123', created=now - timedelta(days=2), full_name='Ada Lovelace')
        make_address('07700 900123', created=now - timedelta(days=1))

        contact = collect_sms_contacts()[0]

        self.assertEqual((contact['first_name'], contact['last_name']), ('Ada', 'Lovelace'))

    def test_it_stays_a_fixed_number_of_queries_however_many_rows(self):
        """The scan is deliberately unindexed; it must not also be an N+1.

        Two queries, not one: the addresses, and one pass over the checkouts
        to find the email attached to each. Neither grows with the row count.
        """
        for i in range(10):
            address = make_address(f'0770090{i:04d}')
            make_checkout(address, email=f'person{i}@example.com')

        with CaptureQueriesContext(connection) as queries:
            contacts = collect_sms_contacts()

        self.assertEqual(len(contacts), 10)
        self.assertEqual(len(queries), 2)


class SmsContactsEndpointTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = get_user_model().objects.create_superuser(
            email='admin@example.com', password='pw'
        )

    def authenticate(self, user):
        token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_anonymous_requests_are_rejected(self):
        make_address('07700 900123')

        response = self.client.get(URL)

        # 401 rather than 403: the JWT authenticator sets a WWW-Authenticate
        # header, so DRF reports "unauthenticated" instead of "forbidden".
        self.assertEqual(response.status_code, 401)

    def test_staff_who_are_not_superusers_are_rejected(self):
        """It is a bulk PII export, so staff alone is not enough."""
        staff = get_user_model().objects.create_user(
            email='staff@example.com', password='pw'
        )
        staff.is_staff = True
        staff.save()
        self.authenticate(staff)

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 403)

    def test_it_counts_distinct_mobiles(self):
        make_address('07700 900123')
        make_address('+44 7700 900123')  # same person, second row
        make_address('07700 900456')
        make_address('020 7946 0958')    # landline

        self.authenticate(self.admin)
        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total'], 2)
        self.assertEqual(len(response.data['contacts']), 2)

    def test_new_last_30_days_counts_numbers_not_rows(self):
        """A repeat order on an old number is not a new contact to text."""
        now = timezone.now()
        make_address('07700 900123', created=now - timedelta(days=60))
        make_address('07700 900123', created=now)  # same number, fresh row
        make_address('07700 900456', created=now - timedelta(days=2))

        self.authenticate(self.admin)
        response = self.client.get(URL)

        self.assertEqual(response.data['total'], 2)
        self.assertEqual(response.data['new_last_30_days'], 1)

    def test_csv_download(self):
        make_address('07700 900123', full_name='Ada Lovelace')
        make_address('020 7946 0958', full_name='Landline Larry')

        self.authenticate(self.admin)
        response = self.client.get(URL, {'format': 'csv'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('sms_contacts.csv', response['Content-Disposition'])

        rows = [
            line for line in response.content.decode().splitlines() if line.strip()
        ]
        self.assertEqual(rows[0], 'Phone,First Name,Last Name,Email')
        self.assertEqual(rows[1], '+447700900123,Ada,Lovelace,')
        self.assertEqual(len(rows), 2)

    def test_csv_quotes_names_containing_commas(self):
        make_address('07700 900123', first_name='Ada', last_name='Lovelace, Countess')

        self.authenticate(self.admin)
        response = self.client.get(URL, {'format': 'csv'})

        self.assertIn('"Lovelace, Countess"', response.content.decode())


class SmsContactEmailTest(TestCase):
    """The export carries the email too, which Address itself does not hold."""

    def test_a_guest_checkout_email_reaches_the_contact(self):
        address = make_address('07700 900123', full_name='Ada Lovelace')
        make_checkout(address, email='ada@example.com')

        contact = collect_sms_contacts()[0]

        self.assertEqual(contact['email'], 'ada@example.com')

    def test_a_logged_in_customer_email_comes_from_the_user(self):
        """CheckoutSession.save nulls `email` when the cart has a user, so
        reading that field alone would lose every account holder's address."""
        user = get_user_model().objects.create_user(
            email='grace@example.com', password='pw'
        )
        address = make_address('07700 900123', full_name='Grace Hopper')
        session = make_checkout(address, user=user)

        self.assertIsNone(session.email)

        contact = collect_sms_contacts()[0]
        self.assertEqual(contact['email'], 'grace@example.com')

    def test_a_contact_with_no_checkout_gets_a_blank_email(self):
        """An SMS export: the phone is the key, so a missing email is not a
        reason to drop the row."""
        make_address('07700 900123')

        contact = collect_sms_contacts()[0]

        self.assertEqual(contact['email'], '')

    def test_the_newest_email_wins_for_a_number_seen_twice(self):
        now = timezone.now()
        old = make_address('07700 900123', created=now - timedelta(days=60))
        new = make_address('+44 7700 900123', created=now)
        make_checkout(old, email='old@example.com', created=now - timedelta(days=60))
        make_checkout(new, email='new@example.com', created=now)

        contacts = collect_sms_contacts()

        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]['email'], 'new@example.com')

    def test_a_later_checkout_without_an_email_does_not_blank_one_we_have(self):
        now = timezone.now()
        address = make_address('07700 900123', created=now - timedelta(days=10))
        make_checkout(address, email='ada@example.com', created=now - timedelta(days=10))

        later = make_address('07700 900123', created=now)
        self.assertIsNotNone(later)

        contacts = collect_sms_contacts()

        self.assertEqual(contacts[0]['email'], 'ada@example.com')

    def test_the_csv_carries_the_email_column(self):
        client = APIClient()
        admin = get_user_model().objects.create_superuser(
            email='admin@example.com', password='pw'
        )
        address = make_address('07700 900123', full_name='Ada Lovelace')
        make_checkout(address, email='ada@example.com')

        token = RefreshToken.for_user(admin).access_token
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        response = client.get(URL, {'format': 'csv'})

        rows = [line for line in response.content.decode().splitlines() if line.strip()]
        self.assertEqual(rows[0], 'Phone,First Name,Last Name,Email')
        self.assertEqual(rows[1], '+447700900123,Ada,Lovelace,ada@example.com')
