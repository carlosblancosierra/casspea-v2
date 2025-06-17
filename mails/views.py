from django.db import transaction
from django.shortcuts import get_object_or_404
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from orders.models import Order
from mails.models import EmailSent, EmailType
from mails.services import OrderShippingMailProcessor
from users.authentication import CustomJWTAuthentication

# cache these to avoid querying per-request
ORDER_CT = ContentType.objects.get_for_model(Order)
SHIPPING_EMAIL_TYPE = EmailType.objects.get(name=EmailType.ORDER_SHIPPING)


class OrderShippingEmailView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def post(self, request):
        # 1. Validate & parse order_id
        try:
            order_id = request.data.get('order_id')
        except (TypeError, ValueError):
            return Response({"error": "Invalid or missing order_id"}, status=status.HTTP_400_BAD_REQUEST)

        # 2. Fetch order or 404
        order = get_object_or_404(Order, order_id=order_id)

        # 3. Permission check
        if order.user != request.user:
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)

        # 4. Business validations
        if not order.tracking_number:
            return Response({"error": "Order has no tracking number"}, status=status.HTTP_400_BAD_REQUEST)

        already_sent = EmailSent.objects.filter(
            content_type=ORDER_CT,
            object_id=order.pk,
            email_type=SHIPPING_EMAIL_TYPE,
            status=EmailSent.SENT,
            is_test=False
        ).exists()
        if already_sent:
            return Response({"error": "Shipping email already sent"}, status=status.HTTP_400_BAD_REQUEST)

        # 5. Log + send within a transaction
        try:
            with transaction.atomic():
                log = EmailSent.objects.create(
                    content_type=ORDER_CT,
                    object_id=order.pk,
                    email_type=SHIPPING_EMAIL_TYPE,
                    status=EmailSent.PENDING,
                    is_test=False
                )
                # send email (consider offloading to Celery/RQ for non-blocking)
                processor = OrderShippingMailProcessor()
                processor.send_shipping_email(order, test=False)

                log.status = EmailSent.SENT
                log.sent = timezone.now()
                log.save(update_fields=['status', 'sent'])
        except Exception as exc:
            # update failure
            if 'log' in locals():
                log.status = EmailSent.FAILED
                log.error_message = str(exc)
                log.save(update_fields=['status', 'error_message'])
            return Response(
                {"error": "Failed to send shipping email"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response({"message": "Shipping email sent successfully"}, status=status.HTTP_200_OK)
