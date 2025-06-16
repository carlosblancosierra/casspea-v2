from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.contenttypes.models import ContentType

from orders.models import Order
from mails.models import EmailSent, EmailType
from mails.services import OrderShippingMailProcessor


class OrderShippingEmailView(APIView):
    def post(self, request):
        order_id = request.data.get('order_id')
        if not order_id:
            return Response({"error": "Order ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            order = Order.objects.get(order_id=order_id)
        except Order.DoesNotExist:
            return Response({"error": "Order not found"}, status=status.HTTP_404_NOT_FOUND)

        if not order.tracking_number:
            return Response({"error": "Order does not have a tracking number"}, status=status.HTTP_400_BAD_REQUEST)

        processor = OrderShippingMailProcessor()
        try:
            processor.send_shipping_email(order, test=False)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"message": "Shipping email sent successfully"}, status=status.HTTP_200_OK)


class OrderEmailLogView(APIView):
    def get(self, request, order_id):
        try:
            order = Order.objects.get(order_id=order_id)
        except Order.DoesNotExist:
            return Response(
                {"error": "Order not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        ct = ContentType.objects.get_for_model(Order)
        logs = EmailSent.objects.filter(
            content_type=ct,
            object_id=order.pk,
            email_type__name=EmailType.ORDER_SHIPPING
        )
        logs_data = [
            {"id": log.pk, "status": log.status, "sent": log.sent, "created": log.created}
            for log in logs
        ]
        return Response(
            logs_data,
            status=status.HTTP_200_OK
        )
