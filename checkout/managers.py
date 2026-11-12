from django.db import models
from django.core.exceptions import ValidationError
import structlog

logger = structlog.get_logger(__name__)

class CheckoutSessionManager(models.Manager):
    def get_or_create_from_request(self, request, create=True):
        """
        Get or create checkout session from request.

        With create=False, return None instead of creating one when the cart
        has no pending session yet.
        """
        from carts.models import Cart

        logger.info(
            "checkout_session_request_started",
            user_id=getattr(request.user, 'id', None),
            session_id=request.session.session_key,
            is_authenticated=request.user.is_authenticated,
            request_data=request.data if hasattr(request, 'data') else None
        )

        try:
            # Use Cart manager to get the active cart
            cart, is_new_cart = Cart.objects.get_or_create_from_request(request)

            logger.info(
                "cart_status_for_checkout",
                cart_id=cart.id,
                is_new_cart=is_new_cart,
                user_id=cart.user_id if cart.user else None,
                session_id=cart.session_id,
                items_count=cart.items.count(),
                cart_active=cart.active
            )

            # Check for non-paid sessions
            existing_sessions = self.filter(
                cart=cart,
                payment_status=self.model.Status.PENDING
            ).select_related('cart')

            logger.debug(
                "existing_sessions_check",
                cart_id=cart.id,
                sessions_count=existing_sessions.count(),
                sessions=[{
                    'id': s.id,
                    'status': s.payment_status,
                    'created': s.created
                } for s in existing_sessions]
            )

            existing_session = existing_sessions.order_by('-created').first()

            if existing_session:
                logger.info(
                    "existing_checkout_session_found",
                    checkout_session_id=existing_session.id,
                    cart_id=cart.id,
                    items_count=cart.items.count(),
                    payment_status=existing_session.payment_status,
                    created=existing_session.created
                )
                # Update email if provided
                if not cart.user and 'email' in request.data:
                    existing_session.email = request.data['email']
                    existing_session.save(update_fields=['email'])
                return existing_session

            if not create:
                return None

            # Create new session
            email = cart.user.email if cart.user else request.data.get('email')

            logger.debug(
                "creating_new_checkout_session",
                cart_id=cart.id,
                email=email,
                user_id=cart.user_id if cart.user else None
            )

            checkout_session = self.create(
                cart=cart,
                email=email
            )

            logger.info(
                "new_checkout_session_created",
                checkout_session_id=checkout_session.id,
                cart_id=cart.id,
                items_count=cart.items.count(),
                is_guest=not cart.user,
                email=email
            )

            return checkout_session

        except Exception as e:
            logger.error(
                "checkout_session_creation_failed",
                error=str(e),
                error_type=type(e).__name__,
                user_id=getattr(request.user, 'id', None),
                session_id=request.session.session_key,
                exc_info=True
            )
            raise

    def validate_session(self, session_id):
        """
        Validate a checkout session is ready for payment.
        """
        try:
            session = self.select_related('cart').get(id=session_id)

            if not session.shipping_address:
                raise ValidationError("Shipping address is required")

            if not session.email and not session.cart.user:
                raise ValidationError("Email is required for guest checkout")

            if not session.cart.items.exists():
                raise ValidationError("Cart is empty")

            if session.payment_status != self.model.Status.PENDING:
                raise ValidationError("Session is not in pending status")

            logger.info(
                "checkout_session_validated",
                checkout_session_id=session.id,
                cart_id=session.cart.id,
                items_count=session.cart.items.count()
            )

            return session

        except self.model.DoesNotExist:
            logger.warning(
                "checkout_session_not_found",
                session_id=session_id
            )
            raise ValidationError("Checkout session not found")
        except ValidationError as e:
            logger.warning(
                "checkout_session_validation_failed",
                session_id=session_id,
                error=str(e)
            )
            raise
