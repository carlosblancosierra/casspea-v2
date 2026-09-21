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

    def test_it_stays_a_single_query_however_many_rows(self):
        """The scan is deliberately unindexed; it must not also be an N+1."""
        for i in range(10):
            make_address(f'0770090{i:04d}')

        with CaptureQueriesContext(connection) as queries:
            contacts = collect_sms_contacts()

        self.assertEqual(len(contacts), 10)
        self.assertEqual(len(queries), 1)


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
        self.assertEqual(rows[0], 'Phone,First Name,Last Name')
        self.assertEqual(rows[1], '+447700900123,Ada,Lovelace')
        self.assertEqual(len(rows), 2)

    def test_csv_quotes_names_containing_commas(self):
        make_address('07700 900123', first_name='Ada', last_name='Lovelace, Countess')

        self.authenticate(self.admin)
        response = self.client.get(URL, {'format': 'csv'})

        self.assertIn('"Lovelace, Countess"', response.content.decode())
