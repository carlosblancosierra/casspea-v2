\
from django.db import models


class Lead(models.Model):
    NEWSLETTER = 'newsletter'
    CONTACT_FORM = 'contact_form'
    LANDING_PAGE = 'landing_page'
    GIVEAWAY = 'giveaway'

    LEAD_TYPES = (
        (NEWSLETTER, 'Newsletter Subscriber'),
        (CONTACT_FORM, 'Contact Form'),
        (LANDING_PAGE, 'Landing Page'),
        (GIVEAWAY, 'Giveaway'),
    )

    email = models.EmailField()
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    instagram_username = models.CharField(max_length=100, blank=True, null=True)
    form_code = models.CharField(max_length=100, blank=True, null=True)

    lead_type = models.CharField(max_length=100, choices=LEAD_TYPES, default=NEWSLETTER)
    unsubscribed = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.email}"


class EmailOptOut(models.Model):
    """An address that asked, through the link in our emails, to get no more
    marketing email: abandoned-cart reminders, review requests, campaigns.

    One row per address, whether or not it ever was a Lead: customers who
    only bought get the same emails and the same right to say no. Order
    confirmations and shipping updates still go out. Delete the row in the
    admin if someone asks to be added back.
    """
    email = models.EmailField(unique=True, help_text="Stored lowercased.")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'email opt-out'

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email
