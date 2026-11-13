from django.template.loader import render_to_string
from django.utils import timezone
from django.conf import settings
from mails.models import EmailType, EmailSent
from django.contrib.contenttypes.models import ContentType
from .models import Lead
from .serializers import LeadSerializer
from rest_framework import generics, status
from rest_framework.response import Response
from django.core.mail import send_mail
from rest_framework.permissions import IsAdminUser
from django.http import HttpResponse
import csv
from rest_framework.views import APIView  # type: ignore
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle
from django.core import signing
import structlog
from .unsubscribe import email_from_token, mask, normalise, opt_out, unsubscribe_url
from .models import EmailOptOut

logger = structlog.get_logger(__name__)


class SubscribeNewsletterView(generics.CreateAPIView):
    """
    Endpoint to subscribe a user to the newsletter.
    """
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'leads'
    serializer_class = LeadSerializer

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        data['lead_type'] = 'newsletter'
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)

        # Signing up here is an explicit request for the newsletter, so it
        # overrides an earlier unsubscribe. Before, the opt-out stayed and the
        # person never got what they had just asked for.
        email = normalise(serializer.validated_data['email'])
        EmailOptOut.objects.filter(email=email).delete()
        Lead.objects.filter(email__iexact=email, lead_type=Lead.NEWSLETTER).update(unsubscribed=False)

        # One newsletter lead per address: signing up twice resends the code
        # instead of adding a duplicate row to the list.
        lead = Lead.objects.filter(email__iexact=email, lead_type=Lead.NEWSLETTER).first()
        if lead is None:
            lead = serializer.save()

        # Get or create EmailType
        email_type, created = EmailType.objects.get_or_create(
            name=EmailType.NEWSLETTER,
        )

        # Render the HTML email template
        html_message = render_to_string('leads/mails/newsletter.html', {'unsubscribe_url': unsubscribe_url(lead.email)})

        subject = 'Newsletter Discount Code'
        from_email = settings.DEFAULT_FROM_EMAIL
        recipient_list = [lead.email]

        try:
            # Send the HTML email
            send_mail(
                subject=subject,
                message='',  # Plain text message can be empty or a fallback
                from_email=from_email,
                recipient_list=recipient_list,
                fail_silently=False,
                html_message=html_message,
            )
            status_email = 'sent'
            sent = timezone.now()
            error_message = None
        except Exception as e:
            status_email = 'failed'
            sent = None
            error_message = str(e)

        # Log the sent email
        EmailSent.objects.create(
            email_type=email_type,
            object_id=lead.id,
            content_type=ContentType.objects.get_for_model(Lead),
            status=status_email,
            sent=sent if status_email == 'sent' else None,
            error_message=error_message if status_email == 'failed' else None,
        )

        # The person is on the list whether or not the email went out. A 500
        # here told them to "try again", which only added duplicates, and it
        # sent the raw mail-server error to the browser. The failure is in
        # EmailSent and the logs for us to resend.
        if status_email == 'failed':
            logger.error("newsletter_email_failed", lead_id=lead.id, error=error_message)

        return Response(
            {'message': 'Successfully subscribed to newsletter'},
            status=status.HTTP_201_CREATED,
        )


class ListLeadsView(generics.ListAPIView):
    """
    Endpoint to list all leads.
    """
    serializer_class = LeadSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        return Lead.objects.all()

# CSV export view


class CSVLeadsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, format=None):
        queryset = Lead.objects.all()
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="leads.csv"'
        writer = csv.writer(response)
        # Dynamically retrieve all field names from the Lead model
        headers = [field.name for field in Lead._meta.fields]
        writer.writerow(headers)
        for lead in queryset:
            writer.writerow([getattr(lead, field) for field in headers])
        return response


class GenericLeadSubscribeView(generics.CreateAPIView):
    """
    Endpoint to subscribe any type of lead. Email is required, other fields are optional.
    """
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'leads'
    serializer_class = LeadSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'message': 'Successfully subscribed'}, status=status.HTTP_201_CREATED)


class SendBlue20View(generics.CreateAPIView):
    serializer_class = LeadSerializer

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        data['lead_type'] = 'landing_page'
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        lead = serializer.save()

        email_type, _ = EmailType.objects.get_or_create(
            name=EmailType.BLUE20,
            defaults={'template_name': 'leads/mails/blue20.html'}
        )
        html_message = render_to_string(
            'leads/mails/blue20.html', {'unsubscribe_url': unsubscribe_url(lead.email)}
        )
        subject = (
            'Your CassPea BLUE20 Discount Code'
        )
        from_email = settings.DEFAULT_FROM_EMAIL
        recipient_list = [lead.email]

        try:
            send_mail(
                subject=subject,
                message='',
                from_email=from_email,
                recipient_list=recipient_list,
                fail_silently=False,
                html_message=html_message,
            )
            status_email = 'sent'
            sent = timezone.now()
            error_message = None
        except Exception as e:
            status_email = 'failed'
            sent = None
            error_message = str(e)

        EmailSent.objects.create(
            email_type=email_type,
            object_id=lead.id,
            content_type=ContentType.objects.get_for_model(Lead),
            status=status_email,
            sent=sent if status_email == 'sent' else None,
            error_message=error_message if status_email == 'failed' else None,
        )

        headers = self.get_success_headers(serializer.data)
        response_data = {'message': 'BLUE20 code sent'}
        if status_email == 'failed':
            response_data['error'] = error_message or "Unknown error"
        return Response(
            response_data,
            status=(
                status.HTTP_201_CREATED
                if status_email == 'sent'
                else status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            headers=headers
        )


class SendGold20View(generics.CreateAPIView):
    serializer_class = LeadSerializer

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        data['lead_type'] = 'landing_page'
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        lead = serializer.save()

        email_type, _ = EmailType.objects.get_or_create(
            name=EmailType.GOLD20,
            defaults={'template_name': 'leads/mails/gold20.html'}
        )
        html_message = render_to_string('leads/mails/gold20.html', {'unsubscribe_url': unsubscribe_url(lead.email)})
        subject = 'Your CassPea GOLD20 Discount Code'
        from_email = settings.DEFAULT_FROM_EMAIL
        recipient_list = [lead.email]

        try:
            send_mail(
                subject=subject,
                message='',
                from_email=from_email,
                recipient_list=recipient_list,
                fail_silently=False,
                html_message=html_message,
            )
            status_email = 'sent'
            sent = timezone.now()
            error_message = None
        except Exception as e:
            status_email = 'failed'
            sent = None
            error_message = str(e)

        EmailSent.objects.create(
            email_type=email_type,
            object_id=lead.id,
            content_type=ContentType.objects.get_for_model(Lead),
            status=status_email,
            sent=sent if status_email == 'sent' else None,
            error_message=error_message if status_email == 'failed' else None,
        )

        headers = self.get_success_headers(serializer.data)
        response_data = {'message': 'GOLD20 code sent'}
        if status_email == 'failed':
            response_data['error'] = error_message or "Unknown error"
        return Response(
            response_data,
            status=(
                status.HTTP_201_CREATED
                if status_email == 'sent'
                else status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            headers=headers
        )


class ThermomixGiveawayEntryView(generics.CreateAPIView):
    serializer_class = LeadSerializer

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        data['lead_type'] = 'giveaway'
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        lead = serializer.save()

        email_type, _ = EmailType.objects.get_or_create(
            name=EmailType.THERMOMIX_GIVEAWAY,
            defaults={'template_name': 'leads/mails/thermomix_giveaway.html'}
        )
        html_message = render_to_string('leads/mails/thermomix_giveaway.html', {'unsubscribe_url': unsubscribe_url(lead.email)})
        subject = 'You’re in the CassPea Thermomix Giveaway!'
        from_email = settings.DEFAULT_FROM_EMAIL
        recipient_list = [lead.email]

        try:
            send_mail(
                subject=subject,
                message='',
                from_email=from_email,
                recipient_list=recipient_list,
                fail_silently=False,
                html_message=html_message,
            )
            status_email = 'sent'
            sent = timezone.now()
            error_message = None
        except Exception as e:
            status_email = 'failed'
            sent = None
            error_message = str(e)

        EmailSent.objects.create(
            email_type=email_type,
            object_id=lead.id,
            content_type=ContentType.objects.get_for_model(Lead),
            status=status_email,
            sent=sent if status_email == 'sent' else None,
            error_message=error_message if status_email == 'failed' else None,
        )

        headers = self.get_success_headers(serializer.data)
        response_data = {'message': 'Giveaway entry confirmed'}
        if status_email == 'failed':
            response_data['error'] = error_message or "Unknown error"
        return Response(
            response_data,
            status=(
                status.HTTP_201_CREATED
                if status_email == 'sent'
                else status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            headers=headers
        )


class UnsubscribeView(APIView):
    """POST /api/leads/unsubscribe/ {"token": "..."}

    The token comes from the link at the bottom of every email (see
    leads/unsubscribe.py). A valid one records the opt-out and answers with
    the address, masked, so the page can confirm whose it was. Posting the
    same token again is fine. The storefront asks for a click first, so link
    scanners that open every URL in an email unsubscribe nobody.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get('token') or ''
        try:
            email = email_from_token(token)
        except signing.BadSignature:
            return Response({'token': 'This unsubscribe link is not valid.'}, status=status.HTTP_400_BAD_REQUEST)
        opt_out(email)
        return Response({'email': mask(email)}, status=status.HTTP_200_OK)
