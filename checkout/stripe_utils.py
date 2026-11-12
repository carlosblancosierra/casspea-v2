
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import stripe
from django.conf import settings
from django.utils import timezone

# Session metadata key prefix for pre-order lines priced inline: one key per
# Stripe product, 'preorder:<product id>' -> the product's own stripe_price_id.
PREORDER_METADATA_PREFIX = 'preorder:'


def to_pence(amount):
    return int((Decimal(amount) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def stripe_line_items(items):
    """Stripe line items for these cart items, each charged at the price the
    cart shows.

    A product on pre-order costs preorder_price in the cart, but its
    stripe_price_id points at whatever price was set up in Stripe, usually
    the regular one, so the customer could see one amount and pay another
    (BUG-18). When the two differ, the line is priced inline at the cart's
    amount, on the same Stripe product, so coupons restricted to that product
    still apply.

    Returns the line items and the metadata that lets the webhook match the
    inline lines back to their products.
    """
    line_items, metadata = [], {}
    for item in items:
        product = item.product
        line = {"quantity": item.quantity, "adjustable_quantity": {"enabled": False}}
        if product.is_preorder_active:
            price = stripe.Price.retrieve(product.stripe_price_id)
            amount = to_pence(product.preorder_price)
            if price.unit_amount != amount:
                price_data = {"currency": price.currency, "product": price.product, "unit_amount": amount}
                if price.tax_behavior in ("inclusive", "exclusive"):
                    price_data["tax_behavior"] = price.tax_behavior
                line["price_data"] = price_data
                metadata[f"{PREORDER_METADATA_PREFIX}{price.product}"] = product.stripe_price_id
                line_items.append(line)
                continue
        line["price"] = product.stripe_price_id
        line_items.append(line)
    return line_items, metadata


def inline_preorder_prices(metadata):
    """{Stripe product id: stripe_price_id} for the lines stripe_line_items
    priced inline, read back from the Checkout Session's metadata."""
    # Since stripe-python 8 a StripeObject is not a dict: .items() and .get()
    # raise AttributeError, so convert it first.
    if isinstance(metadata, stripe.StripeObject):
        metadata = metadata.to_dict()
    if not isinstance(metadata, dict):
        return {}
    return {
        key[len(PREORDER_METADATA_PREFIX):]: value
        for key, value in metadata.items()
        if key.startswith(PREORDER_METADATA_PREFIX)
    }


def prepare_stripe_payload(checkout_session, embedded=False):
    """
    Devuelve el dict de argumentos para stripe.checkout.Session.create,
    con ui_mode='embedded' y return_url si embedded=True,
    o success_url/cancel_url en otro caso.
    """
    # Line items (exclude sold out products)
    items = checkout_session.cart.items.select_related('product').filter(product__sold_out=False)
    line_items, preorder_metadata = stripe_line_items(items)

    if not line_items:
        raise ValueError("Cart has no available items to checkout")

    # Descuentos: misma regla que los totales del carrito (estado activo +
    # pedido mínimo), para que Stripe nunca cobre un total distinto del que
    # vio el cliente.
    discounts = []
    if checkout_session.cart.is_discount_valid:
        discounts = [{"coupon": checkout_session.cart.discount.stripe_id}]

    # Shipping
    shipping_options = [checkout_session.shipping_stripe_format]

    # Invoice creation
    invoice_creation = {
        "enabled": True,
        "invoice_data": {
            "description": "CassPea.co.uk Invoice",
            "footer": "Thank you for your business!",
            "rendering_options": {"amount_tax_display": "include_inclusive_tax"},
        },
    }

    # The storefront Stripe sends the customer back to (settings.SITE_URL).
    base = settings.SITE_URL

    # No payment_method_types here either - same removal, same 400. The methods
    # on offer come from the Stripe Dashboard's payment-method settings.
    payload = {
        "line_items": line_items,
        "customer_email": checkout_session.email,
        "currency": "GBP",
        "mode": "payment",
        "discounts": discounts,
        "shipping_options": shipping_options,
        "client_reference_id": str(checkout_session.id),
        "invoice_creation": invoice_creation,
        "custom_text": {
            "submit": {"message": "We'll send your order confirmation by email."}
        },
        "metadata": {"checkout_session_id": checkout_session.id, **preorder_metadata},
        # Copied onto the PaymentIntent, so payment_intent.* webhooks can find
        # the session too (the session's own metadata stays on the session).
        "payment_intent_data": {"metadata": {"checkout_session_id": str(checkout_session.id)}},
        "expires_at": int((timezone.now() + timedelta(minutes=30)).timestamp()),
    }

    if embedded:
        payload.update({
            "ui_mode": "embedded",
            "return_url": f"{base}/checkout/result?session_id={{CHECKOUT_SESSION_ID}}",
        })
    else:
        payload.update({
            "success_url": f"{base}/checkout/success?session_id={checkout_session.id}",
            "cancel_url":  f"{base}/checkout/cancel?session_id={checkout_session.id}",
        })

    return payload