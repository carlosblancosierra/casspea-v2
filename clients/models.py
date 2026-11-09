"""Private pages for a single client (e.g. a company ordering chocolates).

A ClientPage lists products that only that client may buy. Those products
have ``Product.client_only`` set, which keeps them out of the shop, the
product API and the category pages, and makes the cart refuse them unless the
user is allowed on a page that offers them.
"""
from django.db import models
from storages.backends.s3boto3 import S3Boto3Storage

s3_storage = S3Boto3Storage(location='media')


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
    allowed_emails = models.TextField(
        blank=True, default='',
        help_text="Who may open the page and buy its products, one per line. "
                  "A full address (anna@client.com) or a whole domain "
                  "(@client.com). Empty means staff only.",
    )
    active = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    objects = ClientPageQuerySet.as_manager()

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def _allowed_entries(self):
        return {
            line.strip().lower()
            for line in self.allowed_emails.splitlines()
            if line.strip()
        }

    def allows(self, user):
        """True if this user may see the page and buy its products."""
        if not user or not user.is_authenticated:
            return False
        if user.is_staff:
            return True
        email = (user.email or '').strip().lower()
        if not email or '@' not in email:
            return False
        entries = self._allowed_entries()
        return email in entries or '@' + email.split('@', 1)[1] in entries


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
