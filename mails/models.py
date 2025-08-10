from django.db import models
from django.db.models import Q
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType


class EmailType(models.Model):
    NEWSLETTER = 'newsletter'
    CONTACT = 'contact'
    ORDER_PAID = 'order_paid'
    NON_PAYED_ORDER = 'non_payed_order'
    ORDER_SHIPPING = 'order_shipping'
    REVIEW_REQUEST = 'review_request'

    CHOICES = [
        (NEWSLETTER,      'Newsletter'),
        (CONTACT,         'Contact'),
        (ORDER_PAID,      'Order Paid'),
        (NON_PAYED_ORDER, 'Non-Paid Order'),
        (ORDER_SHIPPING,  'Order Shipping'),
        (REVIEW_REQUEST,  'Review Request'),
    ]

    name = models.CharField(max_length=50, choices=CHOICES, unique=True)
    template_name = models.CharField(max_length=50, unique=True)

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

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    error_message = models.TextField(blank=True, null=True)
    sent = models.DateTimeField(blank=True, null=True)
    is_test = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['content_type', 'object_id', 'email_type']),
        ]

    def __str__(self):
        return f"{self.email_type.name} for {self.content_object} – {self.status}"
