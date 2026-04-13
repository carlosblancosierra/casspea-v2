import uuid
from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType


class EmailType(models.Model):
    NEWSLETTER = 'newsletter'
    CONTACT = 'contact'
    ORDER_PAID = 'order_paid'
    NON_PAYED_ORDER = 'non_payed_order'
    ORDER_SHIPPING = 'order_shipping'
    REVIEW_REQUEST = 'review_request'
    BLUE20 = 'blue20'
    GOLD20 = 'gold20'
    THERMOMIX_GIVEAWAY = 'thermomix_giveaway'

    CHOICES = [
        (NEWSLETTER,      'Newsletter'),
        (CONTACT,         'Contact'),
        (ORDER_PAID,      'Order Paid'),
        (NON_PAYED_ORDER, 'Non-Paid Order'),
        (ORDER_SHIPPING,  'Order Shipping'),
        (REVIEW_REQUEST,  'Review Request'),
        (BLUE20,          'Blue20 Discount'),
        (GOLD20,          'Gold20 Discount'),
        (THERMOMIX_GIVEAWAY, 'Thermomix Giveaway'),
    ]

    name = models.CharField(max_length=50, choices=CHOICES, unique=True)
    template_name = models.CharField(
        max_length=50, unique=True
    )

    def __str__(self):
        return self.name


class EmailSent(models.Model):
    PENDING = 'pending'
    SENT = 'sent'
    FAILED = 'failed'

    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (SENT,    'Sent'),
        (FAILED,  'Failed'),
    ]

    email_type = models.ForeignKey(EmailType, on_delete=models.CASCADE)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    token = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    error_message = models.TextField(blank=True, null=True)
    sent = models.DateTimeField(blank=True, null=True)
    opened = models.DateTimeField(blank=True, null=True)
    is_test = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=[
                    'content_type',
                    'object_id',
                    'email_type',
                ]
            ),
        ]

    def __str__(self):
        return (
            f"{self.email_type.name} for {self.content_object} – "
            f"{self.status}"
        )
