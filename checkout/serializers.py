from django.db import models  # type: ignore
from rest_framework import serializers  # type: ignore
from checkout.models import CheckoutSession
from addresses.serializers import AddressSerializer
from django.utils import timezone # type: ignore
from datetime import timedelta
from addresses.models import Address
from shipping.serializers import ShippingOptionSerializer
from shipping.models import ShippingOption

# Store collection, by what the service *is* rather than by the row's id, which
# differs between environments.
PICKUP_DELIVERY_SPEED = 'PICKUP'

class CheckoutSessionSerializer(serializers.ModelSerializer):
    shipping_address = AddressSerializer(read_only=True)
    billing_address = AddressSerializer(read_only=True)
    cart_total = serializers.DecimalField(
        source='cart.total',
        max_digits=10,
        decimal_places=2,
        read_only=True
    )
    shipping_option = ShippingOptionSerializer(read_only=True)
    shipping_cost = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        read_only=True
    )
    total_with_shipping = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        read_only=True
    )

    class Meta:
        model = CheckoutSession
        fields = '__all__'

    def validate(self, data):
        cart = data.get('cart')
        email = data.get('email')

        if not cart.user and not email:
            raise serializers.ValidationError({
                "email": "Email is required for guest checkout"
            })

        return data

class CheckoutDetailsSerializer(serializers.ModelSerializer):
    shipping_address_id = serializers.IntegerField(required=True)
    billing_address_id = serializers.IntegerField(required=False)
    shipping_option_id = serializers.IntegerField(required=False)

    class Meta:
        model = CheckoutSession
        fields = ['shipping_address_id', 'billing_address_id', 'email', 'phone', 'shipping_option_id']

    def validate(self, data):
        request = self.context['request']

        # Validate shipping address
        shipping_id = data.get('shipping_address_id')
        try:
            if request.user.is_authenticated:
                Address.objects.get(id=shipping_id, user=request.user)
            else:
                Address.objects.get(
                    id=shipping_id,
                    session_key=request.session.session_key,
                    created__gte=timezone.now() - timedelta(hours=24)
                )
        except Address.DoesNotExist:
            raise serializers.ValidationError({
                "shipping_address_id": "Invalid shipping address ID"
            })

        # Validate billing address if provided
        billing_id = data.get('billing_address_id')
        if billing_id:
            try:
                if request.user.is_authenticated:
                    Address.objects.get(id=billing_id, user=request.user)
                else:
                    Address.objects.get(
                        id=billing_id,
                        session_key=request.session.session_key,
                        created__gte=timezone.now() - timedelta(hours=24)
                    )
            except Address.DoesNotExist:
                raise serializers.ValidationError({
                    "billing_address_id": "Invalid billing address ID"
                })

        # Validate shipping option if provided
        shipping_option_id = data.get('shipping_option_id')
        if shipping_option_id:
            try:
                option = ShippingOption.objects.get(
                    id=shipping_option_id,
                    active=True,
                    company__active=True
                )
            except ShippingOption.DoesNotExist:
                raise serializers.ValidationError({
                    "shipping_option_id": "Invalid shipping option ID"
                })

            # A cart holding a fixed-dispatch product cannot be collected: the
            # advent calendars are posted as one batch on a named day, which is
            # the opposite of coming to fetch it whenever. The checkout does not
            # offer collection for such a cart, but a hidden control is not a
            # rule — this is where it becomes one.
            #
            # Matched on delivery_speed rather than the option's id: the id is
            # whatever that row happens to be in this environment, while the
            # speed says what the service is.
            if option.delivery_speed == PICKUP_DELIVERY_SPEED:
                cart = self.instance.cart if self.instance else None
                if cart and cart.fixed_dispatch_date:
                    raise serializers.ValidationError({
                        "shipping_option_id": (
                            "Your order contains an item we post on a fixed day, "
                            "so it cannot be collected in store."
                        )
                    })

        return data

    def update(self, instance, validated_data):
        shipping_id = validated_data.pop('shipping_address_id', None)
        billing_id = validated_data.pop('billing_address_id', None)
        shipping_option_id = validated_data.pop('shipping_option_id', None)

        if shipping_id:
            instance.shipping_address_id = shipping_id
            # Use billing address same as shipping if not provided
            if not billing_id:
                instance.billing_address_id = shipping_id

        if billing_id:
            instance.billing_address_id = billing_id

        if shipping_option_id:
            instance.shipping_option_id = shipping_option_id

        return super().update(instance, validated_data)
