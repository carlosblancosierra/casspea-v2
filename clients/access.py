from rest_framework import serializers

from .models import ClientPage


def user_can_buy(user, product):
    """Anyone can buy a normal product. A client-only product needs a user who
    is allowed on an active client page that offers it."""
    if not product.client_only:
        return True
    pages = ClientPage.objects.active().filter(items__product=product).distinct()
    return any(page.allows(user) for page in pages)


def validate_cart_line(product, quantity, user):
    """Raise a ValidationError if this user can't have this line in the cart."""
    if not user_can_buy(user, product):
        # Same message as a missing product: don't confirm it exists.
        raise serializers.ValidationError({"product": "Product not found"})
    step = product.quantity_step or 1
    if quantity is not None and step > 1 and quantity % step:
        raise serializers.ValidationError({
            "quantity": f"This product is sold in multiples of {step}."
        })
