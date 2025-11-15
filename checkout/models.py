from .managers import CheckoutSessionManager
from shipping.models import ShippingOption
from addresses.models import Address
from django.db import models
from django.contrib.auth import get_user_model
from decimal import Decimal, ROUND_HALF_UP, ROUND_UP
from django.contrib.contenttypes.fields import GenericRelation

User = get_user_model()


# Create your models here.

class CheckoutSession(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending'
        PAID = 'paid'
        FAILED = 'failed'
        CANCELLED = 'cancelled'

    payment_status_choices = [
        (Status.PENDING, 'Pending'),
        (Status.PAID, 'Paid'),
        (Status.FAILED, 'Failed'),
        (Status.CANCELLED, 'Cancelled'),
    ]

    cart = models.ForeignKey('carts.Cart', on_delete=models.CASCADE)

    shipping_address = models.ForeignKey(
        Address,
        related_name='shipping_checkouts',
        on_delete=models.SET_NULL,
        null=True
    )

    billing_address = models.ForeignKey(
        Address,
        related_name='billing_checkouts',
        on_delete=models.SET_NULL,
        null=True
    )

    # Only required for guest checkouts
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    payment_status = models.CharField(
        max_length=20,
        choices=payment_status_choices,
        default=Status.PENDING
    )
    stripe_payment_intent = models.CharField(max_length=255, null=True, blank=True)
    stripe_session_id = models.CharField(max_length=255, null=True, blank=True)

    shipping_option = models.ForeignKey(
        ShippingOption,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    # Add GenericRelation to link EmailSent records
    emailsent = GenericRelation('mails.EmailSent', related_query_name='emailsent')

    objects = CheckoutSessionManager()

    def save(self, *args, **kwargs):
        # If cart has a user, we don't need email/phone
        if self.cart.user:
            self.email = None
            self.phone = None
        # If no user, email is required
        elif not self.email:
            raise ValueError("Email is required for guest checkout")
        super().save(*args, **kwargs)

    @property
    def shipping_cost(self):
        if not self.shipping_option:
            return 0

        # Free shipping logic for options costing £5.00 or less when cart >= £50
        if (self.shipping_option.cents and
                self.shipping_option.cents <= 500 and
                self.cart.discounted_total >= 50):
            return 0

        return self.shipping_option.cents

    @property
    def shipping_cost_pounds(self):
        """Return the shipping cost in pounds, rounded to two decimal places."""
        shipping_cost = self.shipping_cost or 0
        shipping_cost_decimal = Decimal(shipping_cost) / Decimal('100.00')
        return shipping_cost_decimal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def total_with_shipping(self):
        # Ensure that both cart.total and shipping_cost_pounds are Decimals
        cart_total = Decimal(self.cart.total)
        shipping = self.shipping_cost_pounds

        # Calculate the total
        total = cart_total + shipping

        # Round up to two decimal places
        return total.quantize(Decimal('0.01'), rounding=ROUND_UP)

    @property
    def shipping_stripe_format(self):
        if not self.shipping_option:
            return None

        amount = self.shipping_cost
        display_name = self.shipping_option.name
        min_days = self.shipping_option.estimated_days_min
        max_days = self.shipping_option.estimated_days_max

        return {
            "shipping_rate_data": {
                "type": "fixed_amount",
                "fixed_amount": {"amount": amount, "currency": "gbp"},
                "display_name": display_name,
                "delivery_estimate": {
                    "minimum": {"unit": "business_day", "value": min_days},
                    "maximum": {"unit": "business_day", "value": max_days},
                },
            },
        }
