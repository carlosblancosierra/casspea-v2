from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.response import Response
from .models import Address
from .serializers import AddressSerializer
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from checkout.models import CheckoutSession
from rest_framework.views import APIView
from rest_framework.permissions import IsAdminUser
from collections import Counter

import structlog

logger = structlog.get_logger(__name__)

SHIPPING_ADDRESS_EXAMPLE = {
    "full_name": "John Doe",
    "phone": "+44 7700 900000",
    "street_address": "123 Main St",
    "street_address2": "Apt 4B",
    "city": "London",
    "county": "Greater London",
    "postcode": "SW1A 1AA",
    "country": "United Kingdom",
    "place_id": "ChIJdd4hrwug2EcRmSrV3Vo6llI",
    "formatted_address": "123 Main St, London SW1A 1AA, UK",
    "latitude": 51.5074,
    "longitude": -0.1278,
    "address_type": "SHIPPING"
}

BILLING_ADDRESS_EXAMPLE = {
    "full_name": "Carlos Blanco Sierra",
    "phone": "+44 7700 900000",
    "street_address": "123 Main St",
    "street_address2": "Apt 4B",
    "city": "London",
    "county": "Greater London",
    "postcode": "SW1A 1AA",
    "country": "United Kingdom",
    "place_id": "asd123123",
    "formatted_address": "123 Main St, London SW1A 1AA, UK",
    "latitude": 51.5074,
    "longitude": -0.1278,
    "address_type": "BILLING"
}


class AddressViewSet(viewsets.ModelViewSet):
    serializer_class = AddressSerializer

    def get_queryset(self):
        if self.request.user.is_authenticated:
            return Address.objects.filter(user=self.request.user)
        return None

    @extend_schema(
        summary="Create new address",
        description="Creates a shipping or billing address and links it to the active checkout session",
        request=AddressSerializer,
        responses={201: AddressSerializer},
        examples=[
            OpenApiExample(
                'Create Address Example',
                value={
                    "shipping_address": SHIPPING_ADDRESS_EXAMPLE,
                    "billing_address": BILLING_ADDRESS_EXAMPLE
                }
            )
        ]
    )
    def create(self, request):
        try:
            logger.info(
                "address_creation_started",
                user_id=getattr(request.user, 'id', None),
                session_key=request.session.session_key,
                is_authenticated=request.user.is_authenticated
            )

            # Get checkout session
            checkout_session = CheckoutSession.objects.get_or_create_from_request(request)

            if not checkout_session:
                logger.warning("no_active_checkout_session")
                return Response(
                    {"error": "No active checkout session found. Please create a checkout session first."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Process shipping address
            shipping_data = request.data.get('shipping_address')
            if shipping_data:
                shipping_serializer = self.serializer_class(data=shipping_data)
                if not shipping_serializer.is_valid():
                    logger.warning(
                        "shipping_address_validation_failed",
                        errors=shipping_serializer.errors
                    )
                    return Response(
                        {"shipping_address": shipping_serializer.errors},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Save shipping address
                if request.user.is_authenticated:
                    shipping_address = shipping_serializer.save(user=request.user)
                else:
                    shipping_address = shipping_serializer.save()

                checkout_session.shipping_address = shipping_address
                logger.info(
                    "shipping_address_saved",
                    address_id=shipping_address.id,
                    checkout_session_id=checkout_session.id
                )

            # Process billing address
            billing_data = request.data.get('billing_address')
            if billing_data:
                billing_serializer = self.serializer_class(data=billing_data)
                if not billing_serializer.is_valid():
                    logger.warning(
                        "billing_address_validation_failed",
                        errors=billing_serializer.errors
                    )
                    return Response(
                        {"billing_address": billing_serializer.errors},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Save billing address
                if request.user.is_authenticated:
                    billing_address = billing_serializer.save(user=request.user)
                else:
                    billing_address = billing_serializer.save()

                checkout_session.billing_address = billing_address
                logger.info(
                    "billing_address_saved",
                    address_id=billing_address.id,
                    checkout_session_id=checkout_session.id
                )
            elif shipping_data and not checkout_session.billing_address:
                # Use shipping as billing if no billing provided
                checkout_session.billing_address = None
                logger.info("billing_address_set_to_shipping")

            checkout_session.save()
            logger.info(
                "checkout_session_updated",
                checkout_session_id=checkout_session.id,
                shipping_id=getattr(checkout_session.shipping_address, 'id', None),
                billing_id=getattr(checkout_session.billing_address, 'id', None)
            )

            response_data = {
                "shipping_address": shipping_serializer.data if shipping_data else None,
                "billing_address": billing_serializer.data if billing_data else None,
                "checkout_session": {
                    "id": checkout_session.id,
                    "email": checkout_session.email,
                    "cart_id": checkout_session.cart.id,
                    "shipping_address_id": checkout_session.shipping_address_id,
                    "billing_address_id": checkout_session.billing_address_id
                }
            }

            return Response(response_data, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(
                "address_creation_failed",
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class PostalCodeStatsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        if not request.user.is_superuser:
            return Response({'detail': 'Not authorized.'}, status=403)

        paid_orders = CheckoutSession.objects.filter(
            payment_status=CheckoutSession.Status.PAID
        ).select_related('billing_address', 'shipping_address')

        postcodes = []
        for order in paid_orders:
            if order.billing_address and order.billing_address.postcode:
                postcodes.append(order.billing_address.postcode)
            if order.shipping_address and order.shipping_address.postcode:
                postcodes.append(order.shipping_address.postcode)
        postcode_counts = Counter(postcodes)
        # Return as a list of dicts for easier frontend use
        result = [{"postcode": k, "count": v} for k, v in postcode_counts.items()]
        return Response(result)
