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
