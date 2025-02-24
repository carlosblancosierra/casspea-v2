from typing import Dict, List, Optional
import requests
from django.conf import settings
from django.core.exceptions import ValidationError
import structlog

logger = structlog.get_logger(__name__)

class RoyalMailService:
    def __init__(self):
        self.base_url = settings.ROYAL_MAIL_BASE_URL
        self.api_key = settings.ROYAL_MAIL_API_KEY
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

    def create_order(self, order) -> Dict:
        """Create an order in Royal Mail's system"""
        endpoint = f"{self.base_url}/orders"

        # Build recipient details
        recipient = {
            "address": {
                "fullName": order.shipping_address.full_name,
                "addressLine1": order.shipping_address.street_address,
                "addressLine2": order.shipping_address.street_address2,
                "city": order.shipping_address.city,
                "county": order.shipping_address.county,
                "postcode": order.shipping_address.postcode,
                "countryCode": "GB"  # Assuming UK orders for now
            },
            "phoneNumber": order.shipping_address.phone,
            "emailAddress": order.email
        }

        # Build billing details: use billing_address if available; otherwise, fallback to shipping_address.
        billing_address = order.billing_address if order.billing_address else order.shipping_address
        billing = {
            "address": {
                "fullName": billing_address.full_name,
                "addressLine1": billing_address.street_address,
                "addressLine2": billing_address.street_address2,
                "city": billing_address.city,
                "county": billing_address.county,
                "postcode": billing_address.postcode,
                "countryCode": "GB"
            }
        }

        # Determine package format based on service code.
        service_code = order.checkout_session.shipping_option.service_code
        # Use a mapping for service codes to package formats.
        # package_mapping = {
        #     "TPS48": "parcel", 
        #     "TPN24": "parcel", 
        #     "SD1": "parcel", 
        # }
        package_format = "parcel"

        # Build packages data
        packages = []
        for item in order.checkout_session.cart.items.all():
            package = {
                "weightInGrams": (item.product.weight + item.product.box_weight) * item.quantity,
                "packageFormatIdentifier": package_format,
            }
            packages.append(package)

        # Build the request payload
        payload = {
            "items": [{
                "orderReference": order.order_id,
                "recipient": recipient,
                "billing": billing,
                "packages": packages,
                "orderDate": order.created.isoformat(),
                "subtotal": float(order.checkout_session.cart.base_total),
                "shippingCostCharged": float(order.checkout_session.shipping_cost_pounds),
                "total": float(order.checkout_session.total_with_shipping),
                "currencyCode": "GBP",
                "postageDetails": {
                    "sendNotificationsTo": "recipient",
                    "serviceCode": service_code,
                    "receiveEmailNotification": True,
                    "receiveSmsNotification": True if order.shipping_address.phone else False
                },
                "label": {
                    "includeLabelInResponse": True,
                    "includeCN": False,
                    "includeReturnsLabel": False
                }
            }]
        }

        try:
            response = requests.post(endpoint, json=payload, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error("royal_mail_order_creation_failed",
                         error=str(e),
                         order_id=order.order_id)
            raise ValidationError(f"Failed to create Royal Mail order: {str(e)}")

    def get_shipping_label(self, order_identifier: str) -> bytes:
        """Get shipping label PDF for an order"""
        endpoint = f"{self.base_url}/orders/{order_identifier}/label"

        try:
            response = requests.get(
                endpoint,
                headers=self.headers,
                params={
                    "documentType": "postageLabel",
                    "includeReturnsLabel": "false"
                }
            )
            response.raise_for_status()
            return response.content
        except requests.exceptions.RequestException as e:
            logger.error("royal_mail_label_fetch_failed",
                         error=str(e),
                         order_identifier=order_identifier)
            raise ValidationError(f"Failed to fetch shipping label: {str(e)}")
