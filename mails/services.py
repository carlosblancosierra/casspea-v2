from django.utils import timezone
from datetime import timedelta
from checkout.models import CheckoutSession
from mails.models import EmailType, EmailSent
from django.core.mail import EmailMessage, mail_admins
from django.template.loader import render_to_string
from django.conf import settings


class PendingCheckoutSessionsMailProcessor:
    def get_pending_checkout_sessions(self):
        time_delta = timezone.now() - timedelta(days=7)
        
        email_type, _ = EmailType.objects.get_or_create(
            name='non_payed_order',
            defaults={'template_name': 'mails/order_not_paid.html'}
        )
        sessions = CheckoutSession.objects.filter(
            created__gte=time_delta,
            payment_status__in=[
                CheckoutSession.Status.PENDING,
                CheckoutSession.Status.FAILED,
                CheckoutSession.Status.CANCELLED,
            ]
        ).exclude(
            order__isnull=False  # Exclude sessions with associated Orders
        ).filter(
            email__isnull=False
        ).exclude(
            emailsent__email_type=email_type,
            emailsent__is_test=False
        )
        return sessions, email_type

    def build_email(self, session, email_type, test=False):
        subject = "Complete Your CassPea Order and Save 10%!"
        recipient = session.email if not test else "test@test.com"
        context = {
            'checkout_session': session,
            'current_year': timezone.now().year,
        }
        message = render_to_string(email_type.template_name, context)
        email = EmailMessage(
            subject=subject,
            body=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
        )
        email.content_subtype = "html"
        return email

    def log_email_sent(self, session, email_type, is_test=False):
        EmailSent.objects.create(
            email_type=email_type,
            content_object=session,
            is_test=is_test
        )

    def send_pending_mails(self):
        """Real mode: Send emails to each session's email and log them."""
        sessions, email_type = self.get_pending_checkout_sessions()
        for session in sessions:
            email = self.build_email(session, email_type, test=False)
            email.send()
            self.log_email_sent(session, email_type, is_test=False)
        return sessions.count()

    def send_pending_mails_test(self):
        """Test mode: Send the emails to ADMINS using django's mail_admins."""
        sessions, email_type = self.get_pending_checkout_sessions()
        for session in sessions:
            email = self.build_email(session, email_type, test=True)
            mail_admins(email.subject, email.body, html_message=email.body)
            self.log_email_sent(session, email_type, is_test=True)
        return sessions.count()

    def send_pending_mails_dry_run(self):
        """Dry run: Output session details without sending emails or logging."""
        sessions, _ = self.get_pending_checkout_sessions()
        for session in sessions:
            cart = getattr(session, 'cart', None)
            cart_id = getattr(cart, "id", "None")
            cart_total = getattr(cart, "total", "None")
            created = session.created.strftime('%Y-%m-%d %H:%M:%S') if session.created else "Unknown"
            print(
                f"Session ID: {session.id}, Cart ID: {cart_id}, Cart Total: {cart_total}, "
                f"Email: {session.email}, Created: {created}"
            )
        return sessions.count()
