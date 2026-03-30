
from datetime import timedelta
from django.utils import timezone


def prepare_stripe_payload(checkout_session, embedded=False):
    """
    Devuelve el dict de argumentos para stripe.checkout.Session.create,
    con ui_mode='embedded' y return_url si embedded=True,
    o success_url/cancel_url en otro caso.
    """
    # Line items (exclude sold out products)
    items = checkout_session.cart.items.select_related('product').filter(product__sold_out=False)
    line_items = []
    for item in items:
        line_items.append({
            "price": item.product.stripe_price_id,
            "quantity": item.quantity,
            "adjustable_quantity": {"enabled": False},
        })

    # Descuentos
    discounts = []
    if checkout_session.cart.discount and checkout_session.cart.discount.status[0]:
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

    # Dominios
    PROT = "https"
    FRONT = "www.casspea.co.uk"
    base = f"{PROT}://{FRONT}"

    payload = {
        "payment_method_types": ["card"],
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
        "metadata": {"checkout_session_id": checkout_session.id},
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