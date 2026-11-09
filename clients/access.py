"""Who may see a client page and buy its products.

Access is per browser session: entering the page's code stores the page in the
Django session, which is also what identifies the anonymous cart. Staff signed
in to the admin can always see and buy.
"""
from rest_framework import serializers

from .models import ClientPage

SESSION_KEY = 'client_pages'


def unlock(request, page):
    unlocked = dict(request.session.get(SESSION_KEY, {}))
    unlocked[page.slug] = page.access_fingerprint
    request.session[SESSION_KEY] = unlocked


def has_unlocked(request, page):
    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated and user.is_staff:
        return True
    if not page.has_access_code:
        return False
    session = getattr(request, 'session', None)
    unlocked = session.get(SESSION_KEY, {}) if session is not None else {}
    return unlocked.get(page.slug) == page.access_fingerprint


def can_buy(request, product):
    """Anyone can buy a normal product. A client-only product needs a session
    that has unlocked an active client page offering it."""
    if not product.client_only:
        return True
    if request is None:
        return False
    pages = ClientPage.objects.active().filter(items__product=product).distinct()
    return any(has_unlocked(request, page) for page in pages)


def validate_cart_line(product, quantity, request):
    """Raise a ValidationError if this line can't go in this cart."""
    if not can_buy(request, product):
        # Same message as a missing product: don't confirm it exists.
        raise serializers.ValidationError({"product": "Product not found"})
    step = product.quantity_step or 1
    if quantity is not None and step > 1 and quantity % step:
        raise serializers.ValidationError({
            "quantity": f"This product is sold in multiples of {step}."
        })
