from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from .models import Discount


def make_discount(**kwargs):
    defaults = {
        'title': 'Test discount',
        'code': 'TEST',
        'stripe_id': 'TEST',
        'discount_type': Discount.PERCENTAGE,
        'amount': Decimal('10.00'),
        'active': True,
    }
    defaults.update(kwargs)
    return Discount.objects.create(**defaults)


class DiscountStatusTest(TestCase):
    def test_active_discount(self):
        discount = make_discount()
        self.assertEqual(discount.status, (True, 'active'))

    def test_inactive_discount(self):
        discount = make_discount(active=False)
        self.assertEqual(discount.status, (False, 'inactive'))

    def test_scheduled_discount(self):
        discount = make_discount(start_date=timezone.now() + timedelta(days=1))
        self.assertEqual(discount.status, (False, 'scheduled'))

    def test_expired_discount(self):
        discount = make_discount(end_date=timezone.now() - timedelta(days=1))
        self.assertEqual(discount.status, (False, 'expired'))

    def test_discount_within_date_window_is_active(self):
        discount = make_discount(
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=1),
        )
        self.assertEqual(discount.status, (True, 'active'))


class DiscountManagerTest(TestCase):
    def test_get_valid_discounts_filters_correctly(self):
        valid = make_discount(code='VALID')
        make_discount(code='INACTIVE', active=False)
        make_discount(code='EXPIRED', end_date=timezone.now() - timedelta(days=1))
        make_discount(code='SCHEDULED', start_date=timezone.now() + timedelta(days=1))

        valid_codes = list(
            Discount.objects.get_valid_discounts().values_list('code', flat=True)
        )
        self.assertEqual(valid_codes, [valid.code])

    def test_is_valid(self):
        self.assertFalse(Discount.objects.is_valid(None))
        self.assertTrue(Discount.objects.is_valid(make_discount(code='A')))
        self.assertFalse(
            Discount.objects.is_valid(make_discount(code='B', active=False))
        )
