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

        # Discount (threshold + amount) lives in ShippingOption.pricing_for_cart_total
        # so this list and the Stripe charge always agree.
        cart_total = cart.discounted_total if cart else None
        for option in options:
            pricing = option.pricing_for_cart_total(cart_total)
            option._original_price = pricing['original_price']
            option._discounted_price = pricing['discounted_price']
            option._discount_amount = pricing['discount_amount']

        return ShippingOptionSerializer(options, many=True).data


class ShippingOptionSerializer(serializers.ModelSerializer):
    price = serializers.SerializerMethodField()
    original_price = serializers.SerializerMethodField()
    discounted_price = serializers.SerializerMethodField()
    discount_amount = serializers.SerializerMethodField()

    class Meta:
        model = ShippingOption
        fields = [
            'id', 'name', 'delivery_speed',
            'price', 'original_price', 'discounted_price', 'discount_amount',
            'estimated_days_min', 'estimated_days_max',
            'description', 'disabled', 'disabled_reason'
        ]

    def get_price(self, obj):
        # Return the discounted price (what customer pays)
        if hasattr(obj, '_discounted_price'):
            return f"{obj._discounted_price:.2f}"
        return f"{obj.price:.2f}"

    def get_original_price(self, obj):
        # Return the original price before discount
        if hasattr(obj, '_original_price'):
            return f"{obj._original_price:.2f}"
        return f"{obj.price:.2f}"

    def get_discounted_price(self, obj):
        # Alias for price - what customer actually pays
        return self.get_price(obj)

    def get_discount_amount(self, obj):
        # Return the discount amount applied
        if hasattr(obj, '_discount_amount'):
            return f"{obj._discount_amount:.2f}"
        return "0.00"
