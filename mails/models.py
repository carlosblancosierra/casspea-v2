from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

class EmailType(models.Model):
    """
    Represents different types of emails.
    """
    NEWSLETTER = 'newsletter'
    CONTACT = 'contact'
    ORDER_PAID = 'order_paid'

    CHOICES = [
        (NEWSLETTER, 'Newsletter'),
        (CONTACT, 'Contact'),
        (ORDER_PAID, 'Order Paid'),
    ]

    name = models.CharField(
        max_length=50,
        choices=CHOICES,
        unique=True
    )
    template_name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name

class EmailSent(models.Model):
    """
    Logs sent emails with references to associated objects (e.g., Lead, Order).
    """

    PENDING = 'pending'
    SENT = 'sent'
    FAILED = 'failed'

    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (SENT, 'Sent'),
        (FAILED, 'Failed'),
    ]

    email_type = models.ForeignKey(EmailType, on_delete=models.CASCADE)

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)

    error_message = models.TextField(blank=True, null=True)
    sent = models.DateTimeField(blank=True, null=True)
    created = models.DateTimeField(auto_now_add=True)

    # New flag to track if this is a test email log
    is_test = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.email_type.name} for {self.content_object} - {self.status}"
