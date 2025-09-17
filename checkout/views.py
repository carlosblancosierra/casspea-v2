from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django.db import transaction
from checkout.models import CheckoutSession
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from .serializers import CheckoutSessionSerializer, CheckoutDetailsSerializer
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from shipping.models import ShippingOption
import structlog

logger = structlog.get_logger(__name__)


class CheckoutViewSet(viewsets.ViewSet):
    """
    Checkout process management.
    Handles creation and management of checkout sessions.
    """

    @extend_schema(
        summary="Create or update checkout session",
        description="Creates a new checkout session or returns existing one. Email and shipping option are optional.",
        request=CheckoutDetailsSerializer,
        examples=[
            OpenApiExample(
                'Guest Checkout',
                summary="Create checkout session for guest user",
                description="Example of creating a checkout session",
                value={
                    "email": "carlosblancosierra@gmail.com",
                    "shipping_option_id": 3
                },
                request_only=True,
            ),
            OpenApiExample(
                'Guest Checkout Response',
                summary="Successful checkout session creation",
                description="Example response for successful checkout session creation",
                value={
                    "id": 1,
                    "email": "carlosblancosierra@gmail.com",
                    "cart": 1,
                    "payment_status": "PENDING",
                    "cart_total": "99.99",
                    "created": "2024-03-19T12:00:00Z",
                    "updated": "2024-03-19T12:00:00Z"
                },
                response_only=True,
            )
        ],
        responses={
            200: CheckoutSessionSerializer,
            400: OpenApiTypes.OBJECT,
            500: OpenApiTypes.OBJECT
        }
    )
    def create(self, request):
        """
        Create or update checkout session
        POST /api/checkout/
        """
        logger.info(
            "checkout_create_started",
            user_id=getattr(request.user, 'id', None),
            session_id=request.session.session_key
        )

        try:
            checkout_session = CheckoutSession.objects.get_or_create_from_request(request)

            with transaction.atomic():
                logger.debug(
                    "processing_checkout_details",
                    checkout_session_id=checkout_session.id,
                    request_data=request.data
                )

                # Update email if provided in request data, even if empty
                if 'email' in request.data and not request.user.is_authenticated:
                    checkout_session.email = request.data['email']
                    checkout_session.save()

                # Update shipping option if provided
                shipping_option_id = request.data.get('shipping_option_id')
                if shipping_option_id:
                    try:
                        shipping_option = ShippingOption.objects.get(
                            id=shipping_option_id,
                            active=True,
                            company__active=True
                        )
                        checkout_session.shipping_option = shipping_option
                        checkout_session.save()
                    except ShippingOption.DoesNotExist:
                        return Response(
                            {'error': 'Invalid shipping option'},
                            status=status.HTTP_400_BAD_REQUEST
                        )

                logger.info(
                    "checkout_created_successfully",
                    checkout_session_id=checkout_session.id,
                    cart_id=checkout_session.cart.id,
                    user_id=getattr(request.user, 'id', None)
                )

                return Response(
                    CheckoutSessionSerializer(checkout_session).data,
                    status=status.HTTP_200_OK
                )

        except ValidationError as e:
            logger.warning(
                "checkout_validation_error",
                error=str(e.detail),
                user_id=getattr(request.user, 'id', None),
                request_data=request.data
            )
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(
                "checkout_error",
                error=str(e),
                error_type=type(e).__name__,
                user_id=getattr(request.user, 'id', None),
                request_data=request.data,
                exc_info=True
            )
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def retrieve(self, request, pk=None):
        """
        Get checkout session details
        GET /api/checkout/{id}/
        """
        logger.info(
            "checkout_retrieve_started",
            checkout_id=pk,
            user_id=getattr(request.user, 'id', None)
        )

        try:
            checkout_session = CheckoutSession.objects.get(id=pk)

            logger.debug(
                "checkout_session_found",
                checkout_session_id=checkout_session.id,
                cart_id=checkout_session.cart.id
            )

            serializer = CheckoutSessionSerializer(checkout_session)
            return Response(serializer.data)

        except CheckoutSession.DoesNotExist:
            logger.warning(
                "checkout_session_not_found",
                checkout_id=pk,
                user_id=getattr(request.user, 'id', None)
            )
            return Response(
                {'error': 'Checkout session not found'},
                status=status.HTTP_404_NOT_FOUND
            )

    @extend_schema(
        summary="Update shipping option",
        description="Updates the shipping option for the checkout session",
        request={"shipping_option_id": "integer"},
        examples=[
            OpenApiExample(
                'Update Pickup Date and Time',
                summary="Update pickup date and time",
                description="Example of updating pickup date and time",
                value={
                    "pickup_date": "2024-12-25",
                    "pickup_time": "10:00"
                },
                request_only=True,
            )
        ],
        responses={200: CheckoutSessionSerializer}
    )
    @action(detail=True, methods=['post'], url_path='shipping-option')
    def update_shipping_option(self, request, pk=None):
        try:
            checkout_session = CheckoutSession.objects.get(id=pk)
            shipping_option_id = request.data.get('shipping_option_id')

            if not shipping_option_id:
                return Response(
                    {'error': 'shipping_option_id is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                shipping_option = ShippingOption.objects.get(
                    id=shipping_option_id,
                    active=True,
                    company__active=True
                )
            except ShippingOption.DoesNotExist:
                return Response(
                    {'error': 'Invalid shipping option'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            checkout_session.shipping_option = shipping_option

            pickup_date = request.data.get('pickup_date')
            pickup_time = request.data.get('pickup_time')
            logger.info(
                "updating_pickup_date_and_time",
                pickup_date=pickup_date,
                pickup_time=pickup_time
            )
            cart = checkout_session.cart
            if pickup_date and pickup_time:
                try:
                    # Ensure pickup_date is a date object
                    from datetime import datetime
                    if isinstance(pickup_date, str):
                        try:
                            cart.pickup_date = datetime.strptime(pickup_date, "%Y-%m-%d").date()
                        except ValueError as ve:
                            logger.error(
                                "cart_pickup_date_parse_error",
                                error=str(ve),
                                pickup_date=pickup_date
                            )
                            cart.pickup_date = None
                    else:
                        cart.pickup_date = pickup_date
                    cart.pickup_time = pickup_time
                    cart.save()
                    logger.info(
                        "cart_pickup_saved",
                        cart_id=cart.id,
                        pickup_date=str(cart.pickup_date),
                        pickup_time=str(cart.pickup_time)
                    )
                except Exception as e:
                    logger.error(
                        "cart_pickup_save_error",
                        error=str(e),
                        cart_id=cart.id,
                        pickup_date=str(cart.pickup_date),
                        pickup_time=str(cart.pickup_time)
                    )

            checkout_session.save()

            return Response(
                CheckoutSessionSerializer(checkout_session).data,
                status=status.HTTP_200_OK
            )

        except CheckoutSession.DoesNotExist:
            return Response(
                {'error': 'Checkout session not found'},
                status=status.HTTP_404_NOT_FOUND
            )

    @extend_schema(
        summary="Get current checkout session",
        description="Retrieves the current checkout session for the user or creates a new one",
        responses={
            200: CheckoutSessionSerializer,
            500: OpenApiTypes.OBJECT
        }
    )
    def list(self, request):
        """
        Get current checkout session
        GET /api/checkout/session/
        """
        logger.info(
            "checkout_session_requested",
            user_id=getattr(request.user, 'id', None),
            session_id=request.session.session_key
        )

        try:
            checkout_session = CheckoutSession.objects.get_or_create_from_request(request)

            logger.info(
                "checkout_session_retrieved",
                checkout_session_id=checkout_session.id,
                cart_id=checkout_session.cart.id if checkout_session.cart else None
            )

            return Response(
                CheckoutSessionSerializer(checkout_session).data,
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(
                "checkout_session_error",
                error=str(e),
                error_type=type(e).__name__,
                user_id=getattr(request.user, 'id', None),
                exc_info=True
            )
            return Response(
                {'error': 'Failed to retrieve checkout session'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
