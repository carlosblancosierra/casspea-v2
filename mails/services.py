from django.utils import timezone
from datetime import timedelta
from checkout.models import CheckoutSession
from mails.models import EmailType, EmailSent
from django.core.mail import EmailMessage, mail_admins
from django.template.loader import render_to_string
from django.conf import settings
from orders.models import Order
from django.contrib.contenttypes.models import ContentType
from datetime import date
import traceback


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
        subject = "Complete Your CassPea Order and Save 15%!"
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
        """
        Dry run: Output session details without sending emails or logging.
        """
        sessions, _ = self.get_pending_checkout_sessions()
        for session in sessions:
            cart = getattr(session, 'cart', None)
            cart_id = getattr(cart, "id", "None")
            cart_total = getattr(cart, "total", "None")
            created = (
                session.created.strftime('%Y-%m-%d %H:%M:%S')
                if session.created
                else "Unknown"
            )
            print(
                f"Session ID: {session.id}, Cart ID: {cart_id}, "
                f"Cart Total: {cart_total}, Email: {session.email}, "
                f"Created: {created}"
            )
        return sessions.count()


class OrderShippingMailProcessor:
    def build_email(self, order, test=False):
        subject = "Your Order is about to ship!"
        recipient = order.email if not test else "carlosblancosierra@gmail.com"
        context = {
            'order': order,
            'tracking_number': order.tracking_number,
            'current_year': timezone.now().year,
        }
        message = render_to_string("mails/order_shipping.html", context)
        email = EmailMessage(
            subject=subject,
            body=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
        )
        email.content_subtype = "html"
        return email

    def log_email_sent(self, order, is_test=False):
        email_type = EmailType.objects.get(name=EmailType.ORDER_SHIPPING)
        EmailSent.objects.create(
            email_type=email_type,
            content_object=order,
            is_test=is_test,
        )

    def send_shipping_email(self, order, test=False):
        if not order.tracking_number:
            raise ValueError("Order does not have a tracking number.")
        email = self.build_email(order, test=test)
        if test:
            mail_admins(
                email.subject,
                email.body,
                html_message=email.body,
            )
        else:
            email.send()
        self.log_email_sent(order, is_test=test)
        return True


class ReviewRequestMailProcessor:
    def get_eligible_orders(self):
        start_date = date(2025, 7, 1)
        cutoff = timezone.now() - timedelta(days=7)
        review_email_type, _ = EmailType.objects.get_or_create(
            name=EmailType.REVIEW_REQUEST,
            defaults={'template_name': 'mails/review_request.html'}
        )
        order_ct = ContentType.objects.get_for_model(Order)
        # Orders paid >7 days ago, after July 1, 2025,
        # and not already sent a review request
        orders = (
            Order.objects
            .filter(
                created__gte=start_date,
                created__lte=cutoff,
                checkout_session__payment_status='paid',
            )
            .exclude(
                emailsent__email_type=review_email_type,
                emailsent__content_type=order_ct,
            )
        )
        return orders, review_email_type

    def build_email(self, order, email_type, test=False):
        subject = "How was your CassPea order? We'd love your review!"
        recipient = order.email if not test else "test@test.com"
        context = {
            'order': order,
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

    def log_email_sent(self, order, email_type, is_test=False):
        order_ct = ContentType.objects.get_for_model(order.__class__)
        EmailSent.objects.create(
            email_type=email_type,
            content_type=order_ct,
            object_id=order.pk,
            is_test=is_test
        )

    def send_review_requests(self, test=False):
        orders, email_type = self.get_eligible_orders()
        sent_count = 0
        for order in orders:
            email = self.build_email(order, email_type, test=test)
            if test:
                mail_admins(email.subject, email.body, html_message=email.body)
            else:
                email.send()
            self.log_email_sent(order, email_type, is_test=test)
            sent_count += 1
        return sent_count


def send_error_notification_to_admins(
    error_type, error_message, context_data=None
):
    """
    Send error notification to admins.

    Args:
        error_type: Type of error (e.g., 'Stripe Error', '500 Error')
        error_message: The error message
        context_data: Additional context data as a dictionary
    """
    subject = f"CassPea {error_type} Alert"

    # Build the error message body
    body_parts = [
        f"Error Type: {error_type}",
        f"Error Message: {error_message}",
        f"Timestamp: {timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
    ]

    # Add context data if provided
    if context_data:
        body_parts.append("Context Data:")
        for key, value in context_data.items():
            body_parts.append(f"  {key}: {value}")
        body_parts.append("")

    # Add traceback if available
    tb = traceback.format_exc()
    if tb and tb != "NoneType: None\n":
        body_parts.append("Traceback:")
        body_parts.append(tb)

    body = "\n".join(body_parts)

    try:
        mail_admins(
            subject=subject,
            message=body,
            fail_silently=True,  # Don't raise exceptions if email fails
        )
    except Exception as e:
        # Log the error but don't raise to avoid cascading failures
        print(f"Failed to send admin notification email: {str(e)}")
