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
from django.core.mail import send_mail
from erp.settings import STAFF_EMAILS, ADMINS
import structlog
from django.contrib.contenttypes.models import ContentType

# Initialize structlog logger
logger = structlog.get_logger(__name__)

@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META['HTTP_STRIPE_SIGNATURE']
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

    if event and event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        logger.info("Processing checkout.session.completed event", session_id=session.id)
        checkout_session = None
        order = None

        try:
            # Step 1: Retrieve CheckoutSession
            checkout_session_id = session.metadata.get('checkout_session_id')
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

            # Step 2: Create Order FIRST (before marking as paid so retries can still create it)
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

            # Step 3: Mark CheckoutSession as paid (after order exists)
            checkout_session.payment_status = CheckoutSession.Status.PAID
            checkout_session.stripe_payment_intent = session.payment_intent
            checkout_session.stripe_session_id = session.id
            checkout_session.save()
            logger.info("CheckoutSession updated", checkout_session_id=checkout_session_id)

            # Step 4: Mark cart as inactive if still active
            cart = checkout_session.cart
            if cart.active:
                cart.active = False
                cart.save()
                logger.info("Cart marked as inactive", cart_id=cart.id)

            # Step 5: Send confirmation email
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

                    # Render email template
                    html_content = render_to_string('mails/order_paid.html', {
                        'order': order,
                        'current_year': timezone.now().year,
                    })

                    # Get recipient email
                    recipient_email = checkout_session.email or (
                        checkout_session.cart.user.email if checkout_session.cart.user else None
                    )

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

    if event and event['type'] == 'payment_intent.payment_failed':
        session = event['data']['object']
        logger.info("Processing payment_intent.payment_failed event",
            session_id=session.id
        )

        try:
            # Retrieve the CheckoutSession using metadata
            checkout_session_id = session.metadata.get('checkout_session_id')
            checkout_session = CheckoutSession.objects.get(id=checkout_session_id)
            logger.info("CheckoutSession retrieved for failed payment", checkout_session_id=checkout_session_id)

            # Update CheckoutSession status
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
