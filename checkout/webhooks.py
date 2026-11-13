from collections import defaultdict
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import HttpResponse
from django.conf import settings
import stripe
from django.template.loader import render_to_string
from django.utils import timezone
from mails.models import EmailType, EmailSent
from orders.models import Order, OrderStatusHistory
from checkout.models import CheckoutSession
from carts.models import CartItem
from products.models import Product
from django.core.mail import send_mail
from erp.settings import STAFF_EMAILS, ADMINS
import structlog
from django.contrib.contenttypes.models import ContentType
from leads.unsubscribe import unsubscribe_url
from checkout.stripe_utils import inline_preorder_prices

# Initialize structlog logger
logger = structlog.get_logger(__name__)

# Events after which Stripe may have the money. Each is fulfilled only when
# the session's payment_status says so: delayed methods (bank debits,
# vouchers) complete the session as 'unpaid', and the money arrives later
# with async_payment_succeeded, or never (async_payment_failed). A zero
# total, e.g. a 100% coupon, completes as 'no_payment_required'.
FULFILMENT_EVENTS = ('checkout.session.completed', 'checkout.session.async_payment_succeeded')
PAID_STATUSES = ('paid', 'no_payment_required')

@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    # Stripe signs every delivery. A request without the header did not come
    # from Stripe, so it is refused like a bad signature (400), not with a
    # KeyError (500) that would show up as a server error (BUG-11).
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    if not sig_header:
        logger.warning("Webhook call without a Stripe-Signature header")
        return HttpResponse(status=400)
    event = None

    # Get the appropriate webhook secret based on environment
    endpoint_secret = settings.STRIPE_WEBHOOK_SECRET

    # Log the first few characters of the signature and secret for debugging
    logger.info("Webhook Debug Info",
        sig_header_preview=sig_header[:10] if sig_header else None,
        endpoint_secret_preview=endpoint_secret[:10] if endpoint_secret else None,
        payload_preview=payload[:100] if payload else None,
        content_length=request.META.get('CONTENT_LENGTH'),
        content_type=request.META.get('CONTENT_TYPE'),
        request_method=request.method
    )

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
        logger.info("Stripe webhook constructed successfully",
            event_id=event.id,
            event_type=event.type
        )
    except ValueError as e:
        logger.error("Invalid payload", error=str(e))
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError as e:
        logger.error("Signature verification failed",
            error=str(e),
            sig_header=sig_header[:10],
            endpoint_secret_preview=endpoint_secret[:10] if endpoint_secret else None,
            full_sig_header=sig_header  # Log the full signature for debugging
        )
        return HttpResponse(status=400)

    if event and event['type'] in FULFILMENT_EVENTS:
        session = event['data']['object']
        payment_status = getattr(session, 'payment_status', None)
        if payment_status not in PAID_STATUSES:
            # Not paid yet: no order, no confirmation email. Acknowledged so
            # Stripe does not retry; async_payment_succeeded comes back here.
            logger.info("Checkout session completed without payment, waiting",
                        event_type=event['type'], session_id=session.id,
                        payment_status=payment_status)
            return HttpResponse(status=200)
        logger.info("Processing paid checkout session", event_type=event['type'],
                    session_id=session.id, payment_status=payment_status)
        checkout_session = None
        order = None

        try:
            # Step 1: Retrieve CheckoutSession
            checkout_session_id = session.metadata['checkout_session_id']
            try:
                checkout_session = CheckoutSession.objects.get(id=checkout_session_id)

                # Check if this session was already processed
                if checkout_session.payment_status == CheckoutSession.Status.PAID:
                    logger.warning("CheckoutSession already processed",
                        checkout_session_id=checkout_session_id)
                    return HttpResponse(status=200)

            except CheckoutSession.DoesNotExist as csde:
                logger.error("CheckoutSession does not exist",
                    checkout_session_id=checkout_session_id, error=str(csde))
                return HttpResponse(status=404)

            # Step 2: Reconcile cart items with what Stripe actually charged
            try:
                stripe_line_items = stripe.checkout.Session.list_line_items(session.id, limit=100)

                cart = checkout_session.cart
                # Several cart lines can share one Stripe price: two boxes of
                # the same product with different flavours. Compare the total
                # quantity per price, never one line per price, or a correct
                # payment listed in another order looked like a mismatch and a
                # line's quantity was overwritten.
                cart_lines_by_price = defaultdict(list)
                for ci in cart.items.select_related('product').all():
                    cart_lines_by_price[ci.product.stripe_price_id].append(ci)

                # A pre-order line priced inline (BUG-18) carries a one-off
                # price id. The session metadata maps its Stripe product back
                # to the product's own price id, so it is not mistaken for a
                # line the customer did not pay for.
                inline_prices = inline_preorder_prices(getattr(session, 'metadata', None))
                stripe_items = defaultdict(int)
                for item in stripe_line_items.auto_paging_iter():
                    price_id = item.price.id
                    if price_id not in cart_lines_by_price:
                        price_id = inline_prices.get(item.price.product, price_id)
                    stripe_items[price_id] += item.quantity

                cart_totals = {pid: sum(ci.quantity for ci in lines) for pid, lines in cart_lines_by_price.items()}
                needs_reconciliation = cart_totals != dict(stripe_items)

                if needs_reconciliation:
                    logger.info("Cart/Stripe mismatch — reconciling",
                        stripe_items=dict(stripe_items),
                        cart_items=cart_totals,
                    )

                    for price_id in set(cart_totals) | set(stripe_items):
                        charged = stripe_items.get(price_id, 0)
                        lines = cart_lines_by_price.get(price_id, [])
                        if cart_totals.get(price_id, 0) == charged:
                            continue
                        if len(lines) > 1:
                            # Which line changed cannot be told from the price.
                            # Leave them for a person rather than guess.
                            logger.error("Cart/Stripe mismatch on a price shared by several lines — not changed",
                                price_id=price_id, charged=charged,
                                cart_item_ids=[ci.id for ci in lines])
                        elif lines and charged == 0:
                            lines[0].delete()
                            logger.info("Removed cart item absent from Stripe payment",
                                price_id=price_id, cart_item_id=lines[0].id)
                        elif lines:
                            lines[0].quantity = charged
                            lines[0].save()
                            logger.info("Updated cart item quantity to match Stripe",
                                price_id=price_id, quantity=charged)
                        else:
                            try:
                                product = Product.objects.get(stripe_price_id=price_id)
                                CartItem.objects.create(cart=cart, product=product, quantity=charged)
                                logger.info("Added cart item from Stripe payment",
                                    price_id=price_id, quantity=charged)
                            except Product.DoesNotExist:
                                logger.warning("No product found for Stripe price_id — skipping",
                                    price_id=price_id)
                else:
                    logger.info("Cart matches Stripe line items — no reconciliation needed")

            except Exception as reconcile_exc:
                logger.exception("Failed to reconcile cart with Stripe line items",
                    error=str(reconcile_exc))
                # Non-fatal: continue with order creation using existing cart state

            # Step 3: Create Order FIRST (before marking as paid so retries can still create it)
            try:
                order = Order.objects.get(checkout_session=checkout_session)
                logger.info("Order already exists", order_id=order.order_id)
            except Order.DoesNotExist:
                order = Order.objects.create(
                    checkout_session=checkout_session,
                    status='processing'
                )
                logger.info("Order created", order_id=order.order_id)

                # Create initial status history
                OrderStatusHistory.objects.create(
                    order=order,
                    status='processing',
                    notes='Order has been created and is processing.',
                    created_by=checkout_session.cart.user if checkout_session.cart.user else None
                )
                logger.info("OrderStatusHistory logged", order_id=order.order_id)

            # Step 4: Mark CheckoutSession as paid (after order exists)
            checkout_session.payment_status = CheckoutSession.Status.PAID
            checkout_session.stripe_payment_intent = session.payment_intent
            checkout_session.stripe_session_id = session.id
            checkout_session.save()
            logger.info("CheckoutSession updated", checkout_session_id=checkout_session_id)

            # Step 5: Mark cart as inactive if still active
            cart = checkout_session.cart
            if cart.active:
                cart.active = False
                cart.save()
                logger.info("Cart marked as inactive", cart_id=cart.id)

            # Step 6: Send confirmation email
            # Get the content type for Order
            content_type = ContentType.objects.get_for_model(order)

            # Check if email was already sent - Modified query
            if not EmailSent.objects.filter(
                content_type=content_type,
                object_id=order.id,  # Use the actual ID
                email_type__name=EmailType.ORDER_PAID,
                status=EmailSent.SENT
            ).exists():
                email_sent = None
                try:
                    email_type = EmailType.objects.get(name=EmailType.ORDER_PAID)

                    # Create EmailSent entry first
                    email_sent = EmailSent.objects.create(
                        email_type=email_type,
                        content_type=content_type,
                        object_id=order.id,
                        status=EmailSent.PENDING,
                        sent=timezone.now()
                    )

                    # Get recipient email
                    recipient_email = checkout_session.email or (
                        checkout_session.cart.user.email if checkout_session.cart.user else None
                    )

                    # Render email template
                    html_content = render_to_string('mails/order_paid.html', {
                        'order': order,
                        'current_year': timezone.now().year,
                        'unsubscribe_url': unsubscribe_url(recipient_email) if recipient_email else None,
                    })

                    if recipient_email:
                        send_mail(
                            subject='Your CassPea Order Confirmation',
                            message='Thank you for your order!',
                            from_email=settings.DEFAULT_FROM_EMAIL,
                            recipient_list=[recipient_email],
                            html_message=html_content,
                            fail_silently=False,
                        )

                        # Update email status to SENT only after successful sending
                        email_sent.status = EmailSent.SENT
                        email_sent.save()

                        logger.info("Order confirmation email sent",
                            recipient_email=recipient_email,
                            order_id=order.order_id
                        )

                        # Send email to staff
                        staff_html_content = render_to_string('mails/order_paid_staff.html', {
                            'order': order,
                            'current_year': timezone.now().year,
                            # Lets the template link staff straight to the order.
                            'site_url': settings.SITE_URL,
                        })

                        send_mail(
                            subject='New Order Confirmation',
                            message='A new order has been placed',
                            from_email=settings.DEFAULT_FROM_EMAIL,
                            recipient_list=STAFF_EMAILS,
                            html_message=staff_html_content,
                            fail_silently=False,
                        )
                    else:
                        logger.warning("No recipient email found for sending order confirmation", order_id=order.order_id)

                except Exception as email_exc:
                    logger.exception("Failed to send order confirmation email",
                        error=str(email_exc),
                    )
                    if email_sent is not None:
                        email_sent.status = EmailSent.FAILED
                        email_sent.error_message = str(email_exc)
                        email_sent.save()

        except Exception as e:
            logger.exception("Unexpected error during webhook processing", error=str(e))
            return HttpResponse(status=500)

    if event and event['type'] == 'checkout.session.async_payment_failed':
        session = event['data']['object']
        try:
            checkout_session_id = session.metadata['checkout_session_id']
        except (KeyError, TypeError):
            logger.warning("async_payment_failed without checkout_session_id", session_id=session.id)
            return HttpResponse(status=200)
        updated = CheckoutSession.objects.filter(
            id=checkout_session_id, payment_status=CheckoutSession.Status.PENDING,
        ).update(payment_status=CheckoutSession.Status.FAILED)
        logger.info("Delayed payment failed", checkout_session_id=checkout_session_id,
                    marked_failed=bool(updated))
        return HttpResponse(status=200)

    if event and event['type'] == 'payment_intent.payment_failed':
        session = event['data']['object']
        logger.info("Processing payment_intent.payment_failed event",
            session_id=session.id
        )

        # The object is a PaymentIntent. It carries checkout_session_id only
        # when the Checkout Session was created with payment_intent_data
        # metadata; older ones never did, and reading it answered 500 to every
        # such event, so Stripe kept retrying them (BUG-07). Nothing to match:
        # acknowledge.
        try:
            checkout_session_id = session.metadata['checkout_session_id']
        except (KeyError, TypeError, AttributeError):
            logger.info("payment_intent.payment_failed without checkout_session_id, ignored",
                        payment_intent_id=session.id)
            return HttpResponse(status=200)

        try:
            # A declined card can still be retried in the same Checkout, so
            # this never overrides a session that ended up paid.
            checkout_session = CheckoutSession.objects.get(id=checkout_session_id)
            logger.info("CheckoutSession retrieved for failed payment", checkout_session_id=checkout_session_id)

            # Update CheckoutSession status
            if checkout_session.payment_status == CheckoutSession.Status.PENDING:
                checkout_session.payment_status = CheckoutSession.Status.FAILED
                checkout_session.save()
                logger.info("CheckoutSession updated to FAILED", checkout_session_id=checkout_session_id)

        except CheckoutSession.DoesNotExist as csde:
            logger.error("CheckoutSession does not exist for failed payment", checkout_session_id=checkout_session_id, error=str(csde))
            return HttpResponse(status=404)
        except Exception as e:
            logger.exception("Unexpected error during payment failure processing", error=str(e))
            return HttpResponse(status=500)

    return HttpResponse(status=200)
