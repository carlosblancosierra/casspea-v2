"""Private pages for a single client (e.g. a company ordering chocolates).

A ClientPage lists products that only that client may buy. The page is
public but locked with an access code we give the client; no account is
needed. Entering the code unlocks the page for that browser session (the same
Django session the anonymous cart uses).

Products on a page have ``Product.client_only`` set, which keeps them out of
the shop, the product API and the category pages, and makes the cart refuse
them unless the session has unlocked a page that offers them.
"""
from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from storages.backends.s3boto3 import S3Boto3Storage

s3_storage = S3Boto3Storage(location='media')


def normalize_code(raw_code):
    """Codes are typed by people: ignore case and surrounding spaces."""
    return (raw_code or '').strip().upper()


class ClientPageQuerySet(models.QuerySet):
    def active(self):
        return self.filter(active=True)


class ClientPage(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, help_text="Used in the URL: /clients/<slug>")
    logo = models.ImageField(upload_to='clients', storage=s3_storage, null=True, blank=True)
    brand_color = models.CharField(
        max_length=7, blank=True, default='',
        help_text="Client colour as a hex code, e.g. #FF8000. Only used as an accent.",
    )
    welcome_message = models.TextField(blank=True, default='')
    access_code_hash = models.CharField(
        max_length=128, blank=True, default='', editable=False,
        help_text="Hashed access code. Set it from the admin form or "
                  "set_access_code(); the plain code is never stored.",
    )
    active = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    objects = ClientPageQuerySet.as_manager()

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def has_access_code(self):
        return bool(self.access_code_hash)

    def set_access_code(self, raw_code):
        self.access_code_hash = make_password(normalize_code(raw_code))

    def check_access_code(self, raw_code):
        if not self.access_code_hash or not raw_code:
            return False
        return check_password(normalize_code(raw_code), self.access_code_hash)

    @property
    def access_fingerprint(self):
        """Changes whenever the code changes, so a new code locks out
        everyone who unlocked the page with the old one."""
        return self.access_code_hash[-16:]


class ClientPageItem(models.Model):
    page = models.ForeignKey(ClientPage, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(
        'products.Product', on_delete=models.CASCADE, related_name='client_page_items',
    )
    flavour = models.ForeignKey(
        'flavours.Flavour', on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Optional. Lets the page show the flavour's picture and description.",
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['page', 'product'], name='unique_client_page_product'),
        ]

    def __str__(self):
        return f"{self.page} – {self.product}"
