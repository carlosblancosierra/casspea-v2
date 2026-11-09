from rest_framework import serializers

from flavours.models import Flavour
from products.serializers import ProductSerializer

from .models import ClientPage, ClientPageItem


class ClientFlavourSerializer(serializers.ModelSerializer):
    class Meta:
        model = Flavour
        fields = ['id', 'name', 'slug', 'mini_description', 'image']


class ClientPageItemSerializer(serializers.ModelSerializer):
    product = ProductSerializer()
    flavour = ClientFlavourSerializer(allow_null=True)

    class Meta:
        model = ClientPageItem
        fields = ['id', 'product', 'flavour', 'order']


class ClientPageSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()

    class Meta:
        model = ClientPage
        fields = ['name', 'slug', 'logo', 'brand_color', 'welcome_message', 'items']

    def get_items(self, obj):
        items = (
            obj.items.filter(product__active=True)
            .select_related('product', 'product__category', 'flavour')
        )
        return ClientPageItemSerializer(items, many=True, context=self.context).data
