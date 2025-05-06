from rest_framework.views import APIView
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse
from django.shortcuts import redirect
from django.conf import settings
from checkout.models import CheckoutSession
from rest_framework.exceptions import ValidationError
from checkout.stripe_utils import prepare_stripe_payload
import stripe
import structlog
from datetime import timedelta
from django.utils import timezone

logger = structlog.get_logger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY

class StripeCheckoutSessionView(APIView):
    """
    Creates a Stripe Checkout Session and redirects to Stripe's hosted checkout page.
    Requires an active cart and checkout session with shipping address.
    """

    @extend_schema(
        summary="Create Stripe Checkout Session",
        description="""
        Creates a Stripe Checkout Session for the current cart and redirects to Stripe's payment page.
        Requires:
        - Active cart with items
        - Checkout session with shipping address
        - Valid email address

        The user will be redirected to Stripe's hosted checkout page to complete payment.
        """,
        responses={
            200: OpenApiResponse(
                description="Stripe Checkout Session URL"
            ),
            400: OpenApiResponse(
                description="Validation Error",
                response={
                    "type": "object",
                    "properties": {
                        "error": {
                            "type": "string",
                            "example": "Shipping address is required"
                        }
                    }
                }
            ),
            500: OpenApiResponse(
                description="Stripe Error",
                response={
                    "type": "object",
                    "properties": {
                        "error": {
                            "type": "string",
                            "example": "Unable to create checkout session"
                        }
                    }
                }
            )
        },
        tags=["checkout"]
    )
    def post(self, request, *args, **kwargs):
        try:
            # Get or create the checkout session from the request
            checkout_session = CheckoutSession.objects.get_or_create_from_request(request)

            logger.info(
                "checkout_session_retrieved",
                checkout_session_id=checkout_session.id,
                cart_id=checkout_session.cart.id if checkout_session.cart else None
            )

            # Validate shipping address
            if not checkout_session.shipping_address:
                raise ValidationError("Shipping address is required")

            # Retrieve cart items
            cart_items = checkout_session.cart.items.select_related('product').all()

            logger.debug(
                "cart_items_check",
                cart_id=checkout_session.cart.id,
                items_count=cart_items.count(),
                items=[{
                    'id': item.id,
                    'product_id': item.product.id,
                    'quantity': item.quantity,
                    'stripe_price_id': item.product.stripe_price_id
                } for item in cart_items]
            )

            if not cart_items.exists():
                raise ValidationError("Cart is empty")

            # Create line items for Stripe
            line_items = []
            for item in cart_items:
                if not item.product.stripe_price_id:
                    logger.error(
                        "missing_stripe_price",
                        product_id=item.product.id,
                        product_name=item.product.name
                    )
                    raise ValidationError(f"Product {item.product.name} is not configured for payment")

                line_items.append({
                    'price': item.product.stripe_price_id,
                    'quantity': item.quantity,
                    'adjustable_quantity': {
                        'enabled': False,
                    },
                })

            logger.info(
                "line_items_created",
                checkout_session_id=checkout_session.id,
                items_count=len(line_items),
                total_items=sum(item.quantity for item in cart_items)
            )

            # Configure invoice creation
            invoice_creation = {
                "enabled": True,
                "invoice_data": {
                    "description": "CassPea.co.uk Invoice",
                    "footer": "Thank you for your business!",
                    "rendering_options": {
                        "amount_tax_display": "include_inclusive_tax"
                    },
                },
            }

            PROTOCOL = "https"
            API_DOMAIN = "api.casspea.co.uk"
            FRONTEND_DOMAIN = "www.casspea.co.uk"
            FULL_API_DOMAIN = f"{PROTOCOL}://{API_DOMAIN}"
            FULL_FRONTEND_DOMAIN = f"{PROTOCOL}://{FRONTEND_DOMAIN}"

            # Handle discounts
            discounts = []
            if checkout_session.cart.discount and checkout_session.cart.discount.status[0]:
                discounts = [{'coupon': checkout_session.cart.discount.stripe_id}]

            logger.info(
                "shipping_stripe_format",
                checkout_session_id=checkout_session.id,
                shipping_stripe_format=checkout_session.shipping_stripe_format
            )

            shipping_options = [checkout_session.shipping_stripe_format]

            # Create Stripe checkout session
            stripe_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=line_items,
                customer_email=checkout_session.email,
                currency='GBP',
                mode='payment',
                discounts=discounts,
                shipping_options=shipping_options,
                client_reference_id=str(checkout_session.id),
                success_url=f"{FULL_FRONTEND_DOMAIN}/checkout/success?session_id={checkout_session.id}",
                cancel_url=f"{FULL_FRONTEND_DOMAIN}/checkout/cancel?session_id={checkout_session.id}",
                invoice_creation=invoice_creation,
                custom_text={
                    'submit': {
                        'message': 'We\'ll send your order confirmation by email.'
                    }
                },
                metadata={
                    'checkout_session_id': checkout_session.id,
                },
                expires_at=int((timezone.now() + timedelta(minutes=30)).timestamp())
            )

            # Save Stripe session ID to CheckoutSession
            checkout_session.stripe_session_id = stripe_session.id
            checkout_session.save()

            logger.info(
                "stripe_checkout_session_created",
                checkout_session_id=checkout_session.id,
                stripe_session_id=stripe_session.id,
                amount_total=stripe_session.amount_total
            )

            return Response(
                {"url": stripe_session.url},
                status=200
            )

        except ValidationError as e:
            logger.warning(
                "checkout_validation_error",
                error=str(e),
                checkout_session_id=getattr(checkout_session, 'id', None)
            )
            return Response(
                {"error": str(e)},
                status=400
            )

        except stripe.error.StripeError as e:
            logger.error(
                "stripe_error",
                error=str(e),
                checkout_session_id=getattr(checkout_session, 'id', None),
                exc_info=True
            )
            return Response(
                {"error": "Unable to create checkout session"},
                status=500
            )

        except Exception as e:
            logger.error(
                "checkout_creation_failed",
                error=str(e),
                checkout_session_id=getattr(checkout_session, 'id', None),
                exc_info=True
            )
            return Response(
                {"error": "An unexpected error occurred"},
                status=500
            )

class StripeSuccessView(APIView):
    """
    Handles the success URL redirection after a successful Stripe checkout.
    """
    @extend_schema(
        summary="Stripe Checkout Success",
        description="Redirects to the frontend cart page after a successful checkout.",
        responses={302: OpenApiResponse(description="Redirect to frontend cart")}
    )
    def get(self, request, *args, **kwargs):
        session_id = request.GET.get('session_id')
        if not session_id:
            logger.error("Missing session_id in request")
            return redirect(f'https://www.casspea.co.uk/checkout/error?session_id={session_id}')

        try:
            # Verify the session with Stripe
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status == 'paid':
                logger.info("stripe_checkout_success", session_id=session_id)
                return redirect(f'https://www.casspea.co.uk/checkout/success?session_id={session_id}')
            else:
                logger.warning("Payment not completed for session", session_id=session_id)
                return redirect(f'https://www.casspea.co.uk/checkout/error?session_id={session_id}')
        except stripe.error.StripeError as e:
            logger.error("Stripe API error", error=str(e))
            return redirect(f'https://www.casspea.co.uk/checkout/error?session_id={session_id}')

class StripeCancelView(APIView):
    """
    Handles the cancel URL redirection after a cancelled Stripe checkout.
    """
    @extend_schema(
        summary="Stripe Checkout Cancel",
        description="Redirects to the frontend checkout error page after a cancelled checkout.",
        responses={302: OpenApiResponse(description="Redirect to frontend checkout error")}
    )
    def get(self, request, *args, **kwargs):
        session_id = request.GET.get('session_id')
        if session_id:
            logger.info("stripe_checkout_cancel", session_id=session_id)
        else:
            logger.error("Missing session_id in request")

        return redirect(f'https://www.casspea.co.uk/checkout/error?session_id={session_id}')


class StripeCheckoutSessionEmbeddedView(StripeCheckoutSessionView):
    """
    """
    def post(self, request, *args, **kwargs):
        try:
            session = CheckoutSession.objects.get_or_create_from_request(request)
            if not session.shipping_address:
                raise ValidationError("Shipping address is required")

            payload = prepare_stripe_payload(session, embedded=True)
            stripe_sess = stripe.checkout.Session.create(**payload)

            session.stripe_session_id = stripe_sess.id
            session.save()

            return Response({"clientSecret": stripe_sess.client_secret}, status=200)

        except ValidationError as e:
            return Response({"error": str(e)}, status=400)
        except stripe.error.StripeError:
            return Response({"error": "Unable to create checkout session"}, status=500)
        except Exception:
            return Response({"error": "An unexpected error occurred"}, status=500)


class StripeCheckoutResultView(APIView):
    """
    """
    
    def get(self, request, *args, **kwargs):
        session_id = request.GET.get('session_id')
        if not session_id:
            logger.error("Missing session_id in request")
            return Response({"error": "Missing session_id in request"}, status=400)

        try:
            session = stripe.checkout.Session.retrieve(session_id)
            return Response({"status": session.status, "customer_email": session.customer_details.email}, status=200)

        except stripe.error.StripeError as e:
            logger.error("Stripe API error", error=str(e))
            return Response({"error": "Stripe API error"}, status=500)

        except Exception as e:
            logger.error("An unexpected error occurred", error=str(e))
            return Response({"error": "An unexpected error occurred"}, status=500)