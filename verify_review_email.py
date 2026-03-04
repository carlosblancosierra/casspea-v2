import os
import django
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'erp.settings')
django.setup()

from mails.services import ReviewRequestMailProcessor
from orders.models import Order
from django.utils import timezone
from datetime import timedelta

def generate_preview():
    # Find a recent suitable order
    # passing a mock order might be easier if no real data fits the criteria
    
    # Try to find a real order first
    order = Order.objects.filter(
        checkout_session__payment_status='paid',
        checkout_session__cart__items__isnull=False
    ).last()
    
    if not order:
        print("No suitable order found for preview. Please create a test order first.")
        return

    print(f"Generating preview for Order {order.order_id} ({order.email})")
    
    processor = ReviewRequestMailProcessor()
    # We need a dummy email type object or we can mock it
    from mails.models import EmailType
    email_type, _ = EmailType.objects.get_or_create(
        name=EmailType.REVIEW_REQUEST,
        defaults={'template_name': 'mails/review_request.html'}
    )
    
    email = processor.build_email(order, email_type, test=True)
    
    with open('preview_review_email.html', 'w') as f:
        f.write(email.body)
        
    print(f"Preview saved to {os.path.abspath('preview_review_email.html')}")

if __name__ == '__main__':
    generate_preview()
