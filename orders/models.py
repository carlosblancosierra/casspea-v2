from django.db import models
from django.contrib.auth import get_user_model
from django.utils.crypto import get_random_string
from django.utils import timezone
from .managers import OrderManager
from .profanity import ORDER_ID_CHARS, is_offensive
import random
User = get_user_model()


ORDER_ID_LENGTH = 5


def generate_order_id():
    """Generate a unique order ID
    Format: CPYY-XXXXX where:
    - CPYY: CassPea prefix with year
    - XXXXX: Random 5-character alphanumeric string
    Example: CP26-B4K9X

    Orders from before the switch to 5 characters keep their 4-character
    IDs (CP25-B4K9); both share the same unique column, so a new ID can
    never repeat an old one.
    """
    year = timezone.now().strftime("%y")
    prefix = f'CP{year}-'

    # Draw again if the code spells something rude (see orders/profanity.py)
    # or is already taken. Checked here rather than in save(), because the
    # field default fills order_id before save() ever sees it.
    while True:
        random_str = get_random_string(
            length=ORDER_ID_LENGTH, allowed_chars=ORDER_ID_CHARS
        )
        order_id = f'{prefix}{random_str}'
        if is_offensive(random_str):
            continue
        if Order.objects.filter(order_id=order_id).exists():
            continue
        return order_id


class Order(models.Model):
    STATUS_CHOICES = [
        ('processing', 'Processing'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
    ]

    order_id = models.CharField(
        max_length=100,
        unique=True,
        default=generate_order_id,
        editable=False
    )

    # New field to store the Royal Mail order identifier
    shipping_order_id = models.CharField(max_length=100, null=True, blank=True)

    checkout_session = models.OneToOneField(
        'checkout.CheckoutSession',
        on_delete=models.PROTECT,
        related_name='order'
    )

    # Order details
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )

    tracking_number = models.CharField(max_length=100, null=True, blank=True)

    # Timestamps
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    shipped = models.DateTimeField(null=True, blank=True)
    delivered = models.DateTimeField(null=True, blank=True)

    objects = OrderManager()

    class Meta:
        ordering = ['-created']

    def __str__(self):
        return f"Order {self.order_id}"

    @property
    def email(self):
        """Get email from checkout session"""
        return self.checkout_session.email or self.checkout_session.cart.user.email

    @property
    def shipping_address(self):
        """Get shipping address from checkout session"""
        return self.checkout_session.shipping_address

    @property
    def billing_address(self):
        """Get billing address from checkout session"""
        return self.checkout_session.billing_address

    @property
    def payment_status(self):
        """Get payment status from checkout session"""
        return self.checkout_session.payment_status

    @property
    def payment_intent(self):
        """Get Stripe payment intent from checkout session"""
        return self.checkout_session.stripe_payment_intent

    def save(self, *args, **kwargs):
        if not self.order_id:
            self.order_id = generate_order_id()
        super().save(*args, **kwargs)


class OrderStatusHistory(models.Model):
    """Track order status changes"""
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='status_history'
    )
    status = models.CharField(max_length=20)
    notes = models.TextField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    class Meta:
        ordering = ['-created']
        verbose_name_plural = "Order status histories"

    def __str__(self):
        return f"{self.order.order_id} - {self.status}"


class SoldSource(models.Model):
    name = models.CharField(max_length=64)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class UnitsSold(models.Model):
    """
    Stores daily sold chocolates for a given source (e.g., 'ecommerce-v2').
    """
    source_fk = models.ForeignKey(SoldSource, on_delete=models.PROTECT, null=True, blank=True)
    date = models.DateField()
    units_sold = models.PositiveIntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('source_fk', 'date')
        ordering = ['-date', '-created']
        indexes = [
            models.Index(fields=['source_fk', 'date']),
        ]

    def __str__(self):
        return f"{self.source_fk} - {self.date}: {self.units_sold} units"
