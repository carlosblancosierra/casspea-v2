from django.db import models
from django.contrib.auth import get_user_model
from django.utils.crypto import get_random_string
from django.utils import timezone
from .managers import OrderManager
import random
User = get_user_model()

def generate_order_id():
    """Generate a unique order ID
    Format: CPYY-XXXX where:
    - CPYY: CassPea prefix with year
    - XXXX: Random 4-character alphanumeric string
    Example: CP25-B4K9
    """
    year = timezone.now().strftime("%y")
    prefix = f'CP{year}-'

    # Generate a random 4-character string using letters and numbers
    random_str = get_random_string(
        length=4,
        allowed_chars='23456789ABCDEFGHJKLMNPQRSTUVWXYZ'  # Excluding confusing chars like 0,1,I,O
    )

    return f'{prefix}{random_str}'

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

    # check if ID is unique
    def save(self, *args, **kwargs):
        if Order.objects.filter(order_id=self.order_id).exists():
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
