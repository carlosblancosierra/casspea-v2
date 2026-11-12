from django.conf import settings
from django.core.mail import send_mail
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework.response import Response
import structlog

from flavours.models import Flavour
from .models import ChocolateTemplate, PersonalisedRequest
from .serializers import ChocolateTemplateDetailSerializer, PersonalisedRequestSerializer

logger = structlog.get_logger(__name__)


class TemplateListView(APIView):
    def get(self, request, *args, **kwargs):
        templates = ChocolateTemplate.objects.all()
        serializer = ChocolateTemplateDetailSerializer(templates, many=True)
        return Response(serializer.data)


class TemplateDetailView(APIView):
    def get(self, request, slug, *args, **kwargs):
        try:
            template = ChocolateTemplate.objects.get(slug=slug)
        except ChocolateTemplate.DoesNotExist:
            return Response({"error": "Template not found"}, status=404)

        serializer = ChocolateTemplateDetailSerializer(template)
        return Response(serializer.data)


class PersonalisedRequestThrottle(AnonRateThrottle):
    # A real customer sends one; this stops someone filling the inbox.
    scope = 'personalised_request'
    rate = '10/hour'


class PersonalisedRequestView(APIView):
    """POST /api/personalized/send-request/

    Stores the request and emails the team. The storefront has called this
    for a long time; it did not exist, so every request was lost (BUG-05).
    The request is saved first, so a failing email loses nothing.
    """
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PersonalisedRequestThrottle]

    def post(self, request):
        serializer = PersonalisedRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        names = dict(Flavour.objects.filter(id__in=data['flavours']).values_list('id', 'name'))
        personalised = PersonalisedRequest.objects.create(
            template=data['template'],
            email=data['email'],
            comments=data['comments'],
            design=data['custom_design_names'],
            flavours=[names[i] for i in data['flavours'] if i in names],
            quantity=data['quantity'],
        )
        self.notify_staff(personalised)
        return Response({'message': 'Request received'}, status=status.HTTP_201_CREATED)

    @staticmethod
    def notify_staff(personalised):
        lines = [
            f"Template: {personalised.template.title if personalised.template else 'unknown'}",
            f"Quantity: {personalised.quantity}",
            f"Layers, top first: {', '.join(personalised.design) or '-'}",
            f"Flavours: {', '.join(personalised.flavours) or '-'}",
            f"Customer email: {personalised.email}",
            "",
            "Comments:",
            personalised.comments or '-',
            "",
            f"Mark it handled in the admin: request #{personalised.id}.",
        ]
        try:
            send_mail(
                subject=f"Personalised chocolates request from {personalised.email}",
                message='\n'.join(lines),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=settings.STAFF_EMAILS,
                fail_silently=False,
            )
        except Exception:  # noqa: BLE001 - the request is saved; the email is a courtesy
            logger.exception("personalised_request_email_failed", request_id=personalised.id)
