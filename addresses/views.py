from datetime import timedelta

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.response import Response
from .models import Address
from .phones import normalise_uk_mobile, split_name
from .serializers import AddressSerializer
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from checkout.models import CheckoutSession
from rest_framework.views import APIView
from rest_framework.authentication import SessionAuthentication
from rest_framework.renderers import BaseRenderer, BrowsableAPIRenderer, JSONRenderer
from rest_framework.permissions import IsAdminUser
from users.authentication import CustomJWTAuthentication
from collections import Counter
import csv

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
        """
        Get postal code statistics for all paid orders.

        Query parameters:
        - format: 'csv' to download as CSV file, otherwise returns JSON
        """
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

        # Check if CSV format is requested
        # Keyed off the negotiated renderer so both `?format=csv` and an
        # `Accept: text/csv` request get a real CSV rather than a dict handed
        # to a renderer that cannot serialise it.
        if getattr(request.accepted_renderer, 'format', None) == 'csv':
            # Create CSV response
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="postal_code_stats.csv"'

            writer = csv.writer(response)
            writer.writerow(['Postcode', 'Count'])  # Header row

            for postcode, count in sorted(postcode_counts.items()):
                writer.writerow([postcode, count])

            return response
        else:
            # Return as a list of dicts for easier frontend use
            result = [{"postcode": k, "count": v} for k, v in postcode_counts.items()]
            return Response(result)


# How far back "new" reaches, in days.
SMS_NEW_WINDOW_DAYS = 30

# Mailchimp's SMS import expects the number in E.164 plus a name pair.
SMS_CSV_HEADER = ['Phone', 'First Name', 'Last Name']


def collect_sms_contacts():
    """Every distinct UK mobile we hold, newest first.

    Addresses are written one row per checkout attempt - up to two (shipping
    and billing) each time, and nothing deduplicates them - so counting rows
    would badly over-count. We group by the normalised number instead.

    Each contact is {'phone', 'first_name', 'last_name', 'first_seen'}, where
    first_seen is the earliest row carrying that number. Normalisation cannot
    be expressed in SQL, so the grouping happens in Python over a full scan of
    the rows that have a phone at all. There is no index on `phone`; at this
    shop's row count the scan is cheap, and an index would only help if the
    table grew by orders of magnitude.
    """
    rows = (
        Address.objects
        .exclude(phone__isnull=True)
        .exclude(phone__exact='')
        .values('phone', 'first_name', 'last_name', 'full_name', 'created')
        .order_by('created')
        .iterator()
    )

    contacts = {}
    for row in rows:
        number = normalise_uk_mobile(row['phone'])
        if not number:
            continue

        first, last = split_name(row['first_name'], row['last_name'], row['full_name'])
        existing = contacts.get(number)
        if existing is None:
            contacts[number] = {
                'phone': number,
                'first_name': first,
                'last_name': last,
                'first_seen': row['created'],
            }
        elif first or last:
            # Oldest first, so first_seen is already the earliest row and the
            # last name we see is the most recent one the customer gave us.
            # Never overwrite a name with a blank.
            existing['first_name'] = first
            existing['last_name'] = last

    return sorted(contacts.values(), key=lambda c: c['first_seen'], reverse=True)


class CsvRenderer(BaseRenderer):
    """Makes `?format=csv` reach the handler.

    DRF resolves the `format` query parameter against the view's renderers in
    content negotiation, which runs *before* the handler - so a view that has
    no renderer declaring format='csv' answers `?format=csv` with a 404 and
    never writes a byte of CSV. The handler returns a plain HttpResponse,
    which DRF passes through untouched, so render() is never reached in
    practice; it exists so the format is negotiable at all.
    """
    media_type = 'text/csv'
    format = 'csv'
    charset = 'utf-8'

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


class SmsContactsView(APIView):
    """Mobile numbers held, for SMS campaigns.

    Superuser only - it is a bulk export of customer PII.
    """
    permission_classes = [IsAdminUser]
    authentication_classes = [CustomJWTAuthentication, SessionAuthentication]
    # JSON first, so it stays the default when no format is asked for.
    renderer_classes = [JSONRenderer, BrowsableAPIRenderer, CsvRenderer]

    @extend_schema(
        summary="Mobile numbers for SMS campaigns",
        description=(
            "Distinct UK mobile numbers across all saved addresses, with the "
            "count first seen in the last 30 days. `?format=csv` returns a "
            "Mailchimp-shaped CSV instead of JSON."
        ),
        parameters=[
            OpenApiParameter(
                name='format',
                description="Set to 'csv' to download instead of returning JSON.",
                required=False,
                type=str,
            )
        ],
    )
    def get(self, request):
        if not request.user.is_superuser:
            return Response({'detail': 'Not authorized.'}, status=403)

        contacts = collect_sms_contacts()

        if request.query_params.get('format') == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="sms_contacts.csv"'
            writer = csv.writer(response)
            writer.writerow(SMS_CSV_HEADER)
            for contact in contacts:
                writer.writerow([
                    contact['phone'],
                    contact['first_name'],
                    contact['last_name'],
                ])
            return response

        # "New" counts numbers we had never seen before the window opened, not
        # rows written inside it: a repeat customer re-entering the same number
        # is not a new contact to text.
        cutoff = timezone.now() - timedelta(days=SMS_NEW_WINDOW_DAYS)
        new_last_30_days = sum(1 for c in contacts if c['first_seen'] >= cutoff)

        return Response({
            'total': len(contacts),
            'new_last_30_days': new_last_30_days,
            'contacts': contacts,
        })
