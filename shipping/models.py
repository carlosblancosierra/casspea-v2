from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.conf import settings
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP


def is_summer_shipping(today=None):
    """True during the summer ice-pack season (``settings.SUMMER_SHIPPING_MONTHS``).

    In summer, chocolates ship with ice packs: every shipping option costs
    ``SUMMER_ICE_PACK_SURCHARGE`` more, and the over-threshold discount rises to
    ``SUMMER_SHIPPING_DISCOUNT_AMOUNT`` so standard delivery is still free over
    the threshold.
    """
    if today is None:
        today = timezone.localdate()
    return today.month in set(settings.SUMMER_SHIPPING_MONTHS)


class ShippingCompany(models.Model):
    name = models.CharField(max_length=100)
    code = models.SlugField(unique=True)
    active = models.BooleanField(default=True)
    website = models.URLField(blank=True)
    track_url = models.URLField(blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Shipping Companies"

    def __str__(self):
        return self.name


class ShippingOption(models.Model):


    company = models.ForeignKey(
        ShippingCompany,
        on_delete=models.CASCADE,
        related_name='options'
    )
    name = models.CharField(max_length=100)

    delivery_speed = models.CharField(max_length=20)
    price = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    cents = models.PositiveIntegerField(
        null=True,
        blank=True,
        default=499
    )
    estimated_days_min = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(30)]
    )
    estimated_days_max = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(30)]
    )

    service_code = models.CharField(max_length=50, unique=True, null=True, blank=True)

    active = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    disabled = models.BooleanField(default=False)
    disabled_reason = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.company.name} - {self.name}"

    def pricing_for_cart_total(self, cart_total):
        """Single source of truth for this option's price and the cart-total discount.

        Both the shipping-options API (what the customer sees) and the Stripe
        checkout session (what the customer is charged) must call this, so the
        displayed price and the charged price can never diverge. Everything is
        derived from ``price`` so the pound and cent figures always agree.

        ``cart_total`` is the cart's discounted total in pounds (or ``None`` when
        there is no cart, e.g. an anonymous options listing).
        """
        threshold = Decimal(str(settings.SHIPPING_DISCOUNT_THRESHOLD))

        if is_summer_shipping():
            # Ice-pack season: every option costs £1 more, and the discount rises
            # to £6 so standard delivery is still free over the threshold.
            surcharge = Decimal(str(settings.SUMMER_ICE_PACK_SURCHARGE))
            discount = Decimal(str(settings.SUMMER_SHIPPING_DISCOUNT_AMOUNT))
        else:
            surcharge = Decimal('0.00')
            discount = Decimal(str(settings.SHIPPING_DISCOUNT_AMOUNT))

        original = Decimal(self.price) + surcharge

        if cart_total is not None and Decimal(cart_total) >= threshold:
            discounted = max(original - discount, Decimal('0.00'))
        else:
            discounted = original

        applied = original - discounted

        def to_cents(value):
            return int((value * 100).to_integral_value(rounding=ROUND_HALF_UP))

        return {
            'original_price': original,
            'discounted_price': discounted,
            'discount_amount': applied,
            'original_cents': to_cents(original),
            'discounted_cents': to_cents(discounted),
            'discount_cents': to_cents(applied),
        }

    class Meta:
        ordering = ['price']
