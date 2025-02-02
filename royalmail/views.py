from rest_framework import generics, permissions, status
from rest_framework.response import Response
from django.http import HttpResponse
from .services import RoyalMailService
from .serializers import (
    RoyalMailOrderSerializer,
    RoyalMailOrderListSerializer
)
from orders.models import Order
from users.authentication import CustomJWTAuthentication
from rest_framework.authentication import SessionAuthentication
import structlog

logger = structlog.get_logger(__name__)


class RoyalMailOrderListView(generics.ListAPIView):
    """List Royal Mail orders"""
    permission_classes = [permissions.IsAdminUser]
    authentication_classes = [CustomJWTAuthentication, SessionAuthentication]
    serializer_class = RoyalMailOrderListSerializer

    def get_queryset(self):
        return Order.objects.filter(
            tracking_number__isnull=False
        ).select_related(
            'checkout_session',
            'checkout_session__shipping_option'
        )


class RoyalMailOrderCreateView(generics.CreateAPIView):
    """Create Royal Mail shipping label"""
    permission_classes = [permissions.IsAdminUser]
    authentication_classes = [CustomJWTAuthentication, SessionAuthentication]
    serializer_class = RoyalMailOrderSerializer

    def post(self, request, order_id):
        try:
            # Get order
            order = Order.objects.select_related(
                'checkout_session',
                'checkout_session__cart',
                'checkout_session__shipping_address',
                'checkout_session__shipping_option'
            ).get(order_id=order_id)

            # Log order details for debugging
            logger.info(
                "creating_royal_mail_order",
                order_id=order_id,
                shipping_option=order.checkout_session.shipping_option.name
            )

            # Create order in Royal Mail's system
            royal_mail = RoyalMailService()
            response = royal_mail.create_order(order)

            # Log raw response for debugging
            logger.info(
                "royal_mail_api_response",
                order_id=order_id,
                response=response
            )

            # Safely extract data from response
            tracking_number = None
            order_identifier = None
            label_data = None

            if response and isinstance(response, dict):
                created_orders = response.get('createdOrders', [])
                if created_orders and len(created_orders) > 0:
                    first_order = created_orders[0]
                    tracking_number = first_order.get('trackingNumber')
                    order_identifier = first_order.get('orderIdentifier')
                    label_data = first_order.get('label')

            # Update order if we got a tracking number
            if tracking_number and order_identifier:
                order.tracking_number = tracking_number
                order.shipping_order_id = order_identifier
                order.status = 'processing'
                order.save()

                logger.info(
                    "royal_mail_order_created",
                    order_id=order_id,
                    tracking_number=tracking_number
                )
            else:
                logger.error(
                    "royal_mail_no_tracking_number",
                    order_id=order_id,
                    response=response
                )
                return Response(
                    {'error': 'No tracking number received from Royal Mail'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            return Response({
                'success': True,
                'tracking_number': tracking_number,
                'order_identifier': order_identifier,
                'label': label_data
            }, status=status.HTTP_201_CREATED)

        except Order.DoesNotExist:
            logger.error(
                "royal_mail_order_not_found",
                order_id=order_id
            )
            return Response(
                {'error': 'Order not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.exception(
                "royal_mail_order_creation_failed",
                error=str(e),
                order_id=order_id
            )
            return Response({
                'error': 'Failed to create shipping label',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RoyalMailOrderDetailView(generics.RetrieveAPIView):
    """Get Royal Mail order details"""
    permission_classes = [permissions.IsAdminUser]
    authentication_classes = [CustomJWTAuthentication, SessionAuthentication]
    serializer_class = RoyalMailOrderSerializer
    lookup_field = 'order_id'

    def get_queryset(self):
        return Order.objects.filter(tracking_number__isnull=False)


class RoyalMailLabelView(generics.GenericAPIView):
    """Download Royal Mail shipping label"""
    permission_classes = [permissions.IsAdminUser]
    authentication_classes = [CustomJWTAuthentication, SessionAuthentication]

    def get(self, request, order_id):
        try:
            order = Order.objects.get(order_id=order_id)

            # Use shipping_order_id instead of tracking_number
            if not order.shipping_order_id:
                return Response(
                    {'error': 'No shipping label available for this order'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            royal_mail = RoyalMailService()
            # Note: Passing the shipping_order_id here
            label_pdf = royal_mail.get_shipping_label(order.shipping_order_id)

            response = HttpResponse(label_pdf, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="shipping_label_{order.order_id}.pdf"'
            return response

        except Order.DoesNotExist:
            return Response(
                {'error': 'Order not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.exception("royal_mail_label_download_failed", error=str(e))
            return Response(
                {'error': 'Failed to download shipping label'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
