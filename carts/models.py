from django.db import models
from django.conf import settings
from products.models import Product, Allergen
from flavours.models import Flavour
from discounts.models import Discount
from decimal import Decimal, ROUND_UP

from .managers import CartManager


class Cart(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    session_id = models.CharField(max_length=255, null=True, blank=True)
    discount = models.ForeignKey(Discount, null=True, blank=True, on_delete=models.SET_NULL)
    gift_message = models.CharField(max_length=255, null=True, blank=True)
    shipping_date = models.DateField(null=True, blank=True)
    pickup_date = models.DateField(null=True, blank=True)
    pickup_time = models.CharField(null=True, blank=True)

    active = models.BooleanField(default=True)

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    objects = CartManager()

    @property
    def base_total(self):
        """Calculate the total before any discounts"""
        return sum(item.base_price for item in self.items.all())

    @property
    def discounted_total(self):
        """Calculate the total after applying discount"""
        if not self.discount or not self.discount.status[0]:
            return self.base_total

        # For percentage discounts
        if self.discount.discount_type == 'PERCENTAGE':
            non_excluded_total = sum(
                item.base_price
                for item in self.items.all()
                if item.product not in self.discount.exclusions.all()
            )
            excluded_total = self.base_total - non_excluded_total
            discount_amount = (non_excluded_total * self.discount.amount) / 100
            return max(self.base_total - discount_amount, 0)

        # For fixed amount discounts
        return max(self.base_total - self.discount.amount, 0)

    @property
    def total(self):
        return self.discounted_total

    @property
    def total_savings(self):
        """Calculate total amount saved due to discount, rounded up to 2 decimal places"""
        savings = max(self.base_total - self.discounted_total, 0)
        return Decimal(savings).quantize(Decimal('0.01'), rounding=ROUND_UP)

    @property
    def is_discount_valid(self):
        """Check if cart meets minimum order value for discount"""
        if not self.discount:
            return False
        return self.base_total >= self.discount.min_order_value

    class Meta:
        indexes = [
            models.Index(fields=['session_id']),
        ]


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, related_name='items', on_delete=models.CASCADE, null=True, blank=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    @property
    def base_price(self):
        """Calculate the base price for this item"""
        return self.product.base_price * self.quantity

    @property
    def discounted_price(self):
        """Calculate the discounted price if a discount exists"""
        if not self.cart or not self.cart.discount:
            return self.base_price

        # Skip if product is in exclusions
        if self.product in self.cart.discount.exclusions.all():
            return self.base_price

        if self.cart.discount.discount_type == 'PERCENTAGE':
            discount_amount = (self.base_price * self.cart.discount.amount) / 100
            return max(self.base_price - discount_amount, 0)

    @property
    def savings(self):
        """Calculate the amount saved due to discount"""
        if self.discounted_price is None:
            return 0
        return max(self.base_price - self.discounted_price, 0)

    class Meta:
        indexes = [
            models.Index(fields=['cart', 'product']),
        ]


class CartItemBoxCustomization(models.Model):
    SELECTION_TYPE_CHOICES = [
        ('RANDOM', 'Random'),
        ('PICK_AND_MIX', 'Pick and Mix'),
    ]

    cart_item = models.OneToOneField(CartItem, related_name='box_customization', on_delete=models.CASCADE)
    selection_type = models.CharField(max_length=20, choices=SELECTION_TYPE_CHOICES)
    allergens = models.ManyToManyField(Allergen, blank=True)

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.cart_item.product.name} Box Customization"


class CartItemPackCustomization(models.Model):
    SELECTION_TYPE_CHOICES = [
        ('RANDOM', 'Random'),
        ('PICK_AND_MIX', 'Pick and Mix'),
    ]

    cart_item = models.OneToOneField(CartItem, related_name='pack_customization', on_delete=models.CASCADE)
    selection_type = models.CharField(max_length=20, choices=SELECTION_TYPE_CHOICES)
    allergens = models.ManyToManyField(Allergen, blank=True)

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    hot_chocolate = models.ForeignKey(Product, on_delete=models.CASCADE,
                                      null=True, blank=True,
                                      related_name='hot_chocolate_pack_customizations')
    gift_card = models.ForeignKey(Product, on_delete=models.CASCADE, null=True, blank=True,
                                  related_name='gift_card_pack_customizations')
    chocolate_bark = models.ForeignKey(Product, on_delete=models.CASCADE, null=True, blank=True,
                                       related_name='chocolate_bark_pack_customizations')


class CartItemBoxFlavorSelection(models.Model):
    box_customization = models.ForeignKey(
        CartItemBoxCustomization,
        related_name='flavor_selections',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    pack_customization = models.ForeignKey(
        CartItemPackCustomization,    # ← corregido
        on_delete=models.CASCADE,
        related_name='flavor_selections_pack',
        null=True, blank=True
    )
    flavor = models.ForeignKey(Flavour, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.flavor.name} x {self.quantity} in {self.box_customization}"
