from rest_framework import serializers
from .models import ShippingCompany, ShippingOption


class ShippingCompanyWithOptionsSerializer(serializers.ModelSerializer):
    shipping_options = serializers.SerializerMethodField()

    class Meta:
        model = ShippingCompany
        fields = ['id', 'name', 'code', 'website', 'track_url', 'shipping_options']

    def get_shipping_options(self, obj):
        options = obj.options.filter(active=True)
        return ShippingOptionSerializer(options, many=True).data


class ShippingOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShippingOption
        fields = [
            'id', 'name', 'delivery_speed',
            'price', 'estimated_days_min', 'estimated_days_max',
            'description', 'disabled', 'disabled_reason'
        ]
