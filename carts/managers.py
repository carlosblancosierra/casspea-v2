import structlog
from django.db import models
from django.db import transaction

logger = structlog.get_logger(__name__)

class CartManager(models.Manager):
    def for_serialization(self, pk):
        """Fetch a cart with everything CartSerializer touches, so serializing
        a cart is a constant number of queries instead of one per item /
        customization / flavour / allergen."""
        return (
            self.select_related('discount')
            .prefetch_related(
                'discount__exclusions',
                'items__product',
                'items__box_customization__allergens',
                'items__box_customization__flavor_selections__flavor',
                'items__pack_customization__allergens',
                'items__pack_customization__flavor_selections_pack__flavor',
            )
            .get(pk=pk)
        )

    def get_or_create_from_request(self, request):
        """
        Get or create a cart based on session or user.
        """
        logger.info(
            "cart_request_started",
            user_id=getattr(request.user, 'id', None),
            session_id=request.session.session_key,
            is_authenticated=request.user.is_authenticated
        )

        with transaction.atomic():
            if request.user.is_authenticated:
                return self._get_or_create_user_cart(request.user)
            else:
                return self._get_or_create_session_cart(request)

    def _get_or_create_user_cart(self, user):
        """Handle authenticated user carts"""
        # Lock the rows to prevent race conditions
        active_cart = self.select_for_update().filter(
            user=user,
            active=True
        ).first()

        if active_cart:
            logger.info(
                "found_active_user_cart",
                cart_id=active_cart.id,
                user_id=user.id,
                items_count=active_cart.items.count()
            )
            return active_cart, False

        # Create new cart (no reactivation)
        logger.info(
            "creating_new_user_cart",
            user_id=user.id
        )
        return self.create(
            user=user,
            session_id=None,
            active=True
        ), True

    def _get_or_create_session_cart(self, request):
        """Handle anonymous session carts"""
        if not request.session.session_key:
            request.session.create()
            logger.info(
                "created_new_session",
                session_id=request.session.session_key
            )

        # Lock the rows to prevent race conditions
        active_cart = self.select_for_update().filter(
            session_id=request.session.session_key,
            active=True
        ).first()

        if active_cart:
            logger.info(
                "found_active_session_cart",
                cart_id=active_cart.id,
                session_id=request.session.session_key,
                items_count=active_cart.items.count()
            )
            return active_cart, False

        # Create new cart (no reactivation)
        logger.info(
            "creating_new_session_cart",
            session_id=request.session.session_key
        )
        return self.create(
            session_id=request.session.session_key,
            user=None,
            active=True
        ), True
