from django.db import models
from django.conf import settings
from django.utils.text import slugify

User = settings.AUTH_USER_MODEL


class LayerType(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name


class LayerColor(models.Model):
    name = models.CharField(max_length=50, unique=True)
    hex_code = models.CharField(max_length=7, blank=True, null=True)
    slug = models.SlugField(max_length=50, unique=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ChocolateLayer(models.Model):
    """
    A unique combination of (type + color + images).
    E.g. 'base + White', 'brush + Red' etc.
    """
    layer_type = models.ForeignKey(LayerType, on_delete=models.PROTECT)
    color = models.ForeignKey(LayerColor, on_delete=models.PROTECT)
    top_image = models.ImageField(upload_to='chocolates/top/', blank=True, null=True)
    side_image = models.ImageField(upload_to='chocolates/side/', blank=True, null=True)

    def __str__(self):
        return f"{self.layer_type.name} - {self.color.name}"


class ChocolateTemplate(models.Model):
    """
    A 'recipe' specifying which layer types (and in what order/label) belong to this template.
    e.g. slot #1 => 'base', slot #2 => 'brush'
    """
    title = models.CharField(max_length=120, unique=True)
    layer_slots = models.ManyToManyField(
        LayerType,
        through='TemplateLayerSlot',
        related_name='templates'
    )
    slug = models.SlugField(max_length=120, unique=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class TemplateLayerSlot(models.Model):
    """
    Through-model for ChocolateTemplate <-> LayerType
    Allows specifying order and an optional label for each slot.
    """
    template = models.ForeignKey(ChocolateTemplate, on_delete=models.CASCADE)
    layer_type = models.ForeignKey(LayerType, on_delete=models.PROTECT)
    name = models.CharField(max_length=120, blank=True, null=True, help_text="Label for this slot")
    order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.template.title} - Slot {self.order} ({self.layer_type.name})"


class UserChocolateDesign(models.Model):
    """
    The user's final custom choice for each slot.
    M2M to ChocolateLayer via an intermediate model to store order or other info.
    """
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    template = models.ForeignKey(ChocolateTemplate, on_delete=models.PROTECT)

    chosen_layers = models.ManyToManyField(
        ChocolateLayer,
        through='UserChosenLayer',
        related_name='user_designs'
    )

    active = models.BooleanField(default=True)
    featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Design by {self.user} - {self.template.title}"


class UserChosenLayer(models.Model):
    """
    Through-model for storing which ChocolateLayer the user chose for each slot
    and in what order.
    """
    user_design = models.ForeignKey(UserChocolateDesign, on_delete=models.CASCADE, related_name='slots')
    chocolate_layer = models.ForeignKey(ChocolateLayer, on_delete=models.PROTECT)
    order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.user_design} - Layer {self.order} ({self.chocolate_layer})"

class PersonalisedRequest(models.Model):
    """A customer asking for personalised chocolates from /personalised/<slug>.

    The storefront has posted these to /api/personalized/send-request/ for a
    long time, but the endpoint did not exist, so every request was lost
    (BUG-05). Kept here so none is lost again, even if the staff email fails.
    """
    template = models.ForeignKey(ChocolateTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    email = models.EmailField()
    comments = models.TextField(blank=True)
    design = models.JSONField(default=list, blank=True, help_text="Colour chosen for each layer, top first.")
    flavours = models.JSONField(default=list, blank=True, help_text="Names of the flavours asked for.")
    quantity = models.PositiveIntegerField()
    handled = models.BooleanField(default=False, help_text="Tick once someone has replied.")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created']

    def __str__(self):
        return f"{self.email} - {self.template or 'unknown template'} x {self.quantity}"
