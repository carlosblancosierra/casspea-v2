from django.db import models
from allergens.models import Allergen
from django.core.files.storage import default_storage
from django.utils import timezone
from django.utils.text import slugify
from storages.backends.s3boto3 import S3Boto3Storage

# Create S3 storage instance
s3_storage = S3Boto3Storage(location='media')

# Create your models here.


class FlavourCategoryManager(models.Manager):
    def active(self):
        return self.filter(active=True)


class FlavourCategory(models.Model):
    name = models.CharField(max_length=255)
    active = models.BooleanField(default=True)
    slug = models.SlugField(unique=True)

    # A launch date for the whole category, e.g. the Christmas flavours on
    # 1 December. Until then its flavours are shown as "coming soon" and cannot
    # be picked into a box; from that day on they are ordinary flavours. On the
    # category rather than on each flavour so one date launches them all.
    available_from = models.DateField(
        null=True, blank=True,
        help_text="Flavours in this category show as 'Coming soon' and cannot be "
                  "picked into a box before this date. Leave empty for flavours "
                  "on sale now.",
    )

    # Shows the category as its own section, above the other flavours, on the
    # home page and the flavours page.
    featured = models.BooleanField(
        default=False,
        help_text="Show this category as its own section on the home page and "
                  "the flavours page.",
    )
    featured_title = models.CharField(
        max_length=255, blank=True, default='',
        help_text="Section heading, e.g. 'New Christmas Flavours'. Defaults to the "
                  "category name.",
    )
    featured_message = models.TextField(
        blank=True, default='',
        help_text="Line under the heading, e.g. 'Arriving 1 December — and inside "
                  "every Advent Calendar.'",
    )
    featured_cta_label = models.CharField(
        max_length=100, blank=True, default='',
        help_text="Optional button under the section, e.g. 'Shop the Advent Calendar'.",
    )
    featured_cta_url = models.CharField(
        max_length=255, blank=True, default='',
        help_text="Where the button goes, e.g. /shop-now/advent-calendar.",
    )

    objects = FlavourCategoryManager()

    class Meta:
        verbose_name_plural = 'flavour categories'

    def __str__(self):
        return self.name

    @property
    def is_coming_soon(self):
        return bool(self.available_from and self.available_from > timezone.localdate())


class FlavourManager(models.Manager):
    def active(self):
        return self.filter(active=True)

    def purchasable(self):
        """Active flavours that can be picked into a box today: not in a
        category whose launch date is still ahead."""
        today = timezone.localdate()
        return self.active().exclude(category__available_from__gt=today)


class Flavour(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    description = models.TextField()
    mini_description = models.TextField()
    # Long-form copy for the flavour page's full-width rows. Optional: the page
    # falls back to `description` (one sentence) when this is empty.
    story = models.TextField(blank=True, default='')
    allergens = models.ManyToManyField(Allergen)
    featured = models.BooleanField(default=False)
    featured_message = models.TextField(null=True, blank=True)

    # Main images
    image = models.ImageField(
        upload_to='flavours',
        storage=s3_storage,
        help_text="Main product image",
        null=True,
        blank=True
    )

    category = models.ForeignKey(FlavourCategory, on_delete=models.CASCADE, default=1)
    active = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    objects = FlavourManager()

    def __str__(self):
        return self.name

    @property
    def is_coming_soon(self):
        return self.category.is_coming_soon

    class Meta:
        ordering = ['name']


class FlavourSelection(models.Model):
    flavour = models.ForeignKey(Flavour, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1)

    def __str__(self):
        return f"{self.flavour.name} x {self.quantity}"


class FlavourBox(models.Model):
    selections = models.ManyToManyField(FlavourSelection)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Box {self.id}"
