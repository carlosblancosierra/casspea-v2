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


class SubscribeNewsletterView(generics.CreateAPIView):
    """
    Endpoint to subscribe a user to the newsletter.
    """
    serializer_class = LeadSerializer

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        data['lead_type'] = 'newsletter'
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        lead = serializer.save()

        # Get or create EmailType
        email_type, created = EmailType.objects.get_or_create(
            name=EmailType.NEWSLETTER,
        )

        # Render the HTML email template
        html_message = render_to_string('leads/mails/newsletter.html', {})

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
        email_sent = EmailSent.objects.create(
            email_type=email_type,
            object_id=lead.id,
            content_type=ContentType.objects.get_for_model(Lead),
            status=status_email,
            sent=sent if status_email == 'sent' else None,
            error_message=error_message if status_email == 'failed' else None,
        )

        headers = self.get_success_headers(serializer.data)
        response_data = {'message': 'Successfully subscribed to newsletter'}

        if status_email == 'failed':
            response_data['error'] = error_message

        return Response(
            response_data,
            status=status.HTTP_201_CREATED if status_email == 'sent' else status.HTTP_500_INTERNAL_SERVER_ERROR,
            headers=headers
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
