from rest_framework import serializers
from .models import ShippingCompany, ShippingOption
from carts.models import Cart


class ShippingCompanyWithOptionsSerializer(serializers.ModelSerializer):
    shipping_options = serializers.SerializerMethodField()

    class Meta:
        model = ShippingCompany
        fields = ['id', 'name', 'code', 'website', 'track_url', 'shipping_options']

    def get_shipping_options(self, obj):
        request = self.context.get('request')
        if request:
            cart, _ = Cart.objects.get_or_create_from_request(request)
        else:
            cart = None

        options = obj.options.filter(active=True)

        # Apply free shipping logic
        if cart and cart.discounted_total >= 50:
            for option in options:
                if option.cents and option.cents <= 500:
                    # Temporarily modify the price for serialization
                    option._free_shipping_price = True

        return ShippingOptionSerializer(options, many=True).data


class ShippingOptionSerializer(serializers.ModelSerializer):
    price = serializers.SerializerMethodField()

    class Meta:
        model = ShippingOption
        fields = [
            'id', 'name', 'delivery_speed',
            'price', 'estimated_days_min', 'estimated_days_max',
            'description', 'disabled', 'disabled_reason'
        ]

    def get_price(self, obj):
        # Check if this option should be free
        if hasattr(obj, '_free_shipping_price') and obj._free_shipping_price:
            return "0.00"
        return str(obj.price)
