from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class ShippingCompany(models.Model):
    name = models.CharField(max_length=100)
    code = models.SlugField(unique=True)
    active = models.BooleanField(default=True)
    website = models.URLField(blank=True)
    track_url = models.URLField(blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Shipping Companies"

    def __str__(self):
        return self.name


class ShippingOption(models.Model):


    company = models.ForeignKey(
        ShippingCompany,
        on_delete=models.CASCADE,
        related_name='options'
    )
    name = models.CharField(max_length=100)

    delivery_speed = models.CharField(max_length=20)
    price = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    cents = models.PositiveIntegerField(
        null=True,
        blank=True,
        default=499
    )
    estimated_days_min = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(30)]
    )
    estimated_days_max = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(30)]
    )

    service_code = models.CharField(max_length=50, unique=True, null=True, blank=True)

    active = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    disabled = models.BooleanField(default=False)
    disabled_reason = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.company.name} - {self.name}"

    class Meta:
        ordering = ['price']
