from django.db import models
from allergens.models import Allergen
from django.core.files.storage import default_storage
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

    objects = FlavourCategoryManager()

    def __str__(self):
        return self.name


class FlavourManager(models.Manager):
    def active(self):
        return self.filter(active=True)


class Flavour(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    description = models.TextField()
    mini_description = models.TextField()
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
