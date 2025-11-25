from rest_framework import serializers
from .models import Order
from checkout.models import CheckoutSession
from addresses.serializers import AddressSerializer
from carts.models import (
    Cart,
    CartItem,
    CartItemBoxCustomization,
    CartItemBoxFlavorSelection,
    CartItemPackCustomization,
)
from products.models import Product
from checkout.models import ShippingOption
from carts.serializers import (
    CartItemBoxCustomizationSerializer,
    CartItemPackCustomizationSerializer,
    CartItemSerializer,
    CartSerializer,
)


class OrderProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            'id',
            'name',
            'weight',
            'units_per_box',
            'main_color',
            'secondary_color',
            'thumbnail',
        ]


class CartItemBoxFlavorSelectionSerializer(serializers.ModelSerializer):
    flavor_name = serializers.CharField(source='flavor.name')

    class Meta:
        model = CartItemBoxFlavorSelection
        fields = ['id', 'flavor_name', 'quantity']

class CartItemSerializer(serializers.ModelSerializer):
    product = OrderProductSerializer()
    box_customization = CartItemBoxCustomizationSerializer()
    pack_customization = CartItemPackCustomizationSerializer()
    base_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    discounted_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    savings = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = CartItem
        fields = [
            'id',
            'quantity',
            'product',
            'box_customization',
            'pack_customization',
            'base_price',
            'discounted_price',
            'savings'
        ]


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    discount = serializers.CharField(
        source='discount.code', read_only=True
    )
    gift_message = serializers.CharField(
        max_length=255, required=False, allow_blank=True, allow_null=True
    )
    shipping_date = serializers.DateField(required=False, allow_null=True)
    base_total = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    discounted_total = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    total_savings = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = Cart
        fields = [
            'id',
            'items',
            'discount',
            'gift_message',
            'shipping_date',
            'pickup_date',
            'pickup_time',
            'base_total',
            'discounted_total',
            'total_savings',
        ]

    def get_total(self, obj):
        return str(
            sum(
                item.quantity * item.product.current_price
                for item in obj.items.all()
            )
        )


class ShippingOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShippingOption
        fields = ['id', 'name', 'price']


class CheckoutSessionSerializer(serializers.ModelSerializer):
    shipping_address = AddressSerializer()
    billing_address = AddressSerializer()
    shipping_option = ShippingOptionSerializer()

    # Add these method fields to match the model properties
    shipping_cost = serializers.SerializerMethodField()
    shipping_cost_pounds = serializers.SerializerMethodField()
    total_with_shipping = serializers.SerializerMethodField()
    shipping_stripe_format = serializers.SerializerMethodField()

    cart = CartSerializer()

    class Meta:
        model = CheckoutSession
        fields = [
            'id',
            'cart',
            'shipping_address',
            'billing_address',
            'email',
            'phone',
            'created',
            'updated',
            'payment_status',
            'stripe_payment_intent',
            'stripe_session_id',
            'shipping_option',
            'shipping_cost',
            'shipping_cost_pounds',
            'total_with_shipping',
            'shipping_stripe_format'
        ]

    def get_shipping_cost(self, obj):
        return obj.shipping_cost

    def get_shipping_cost_pounds(self, obj):
        return obj.shipping_cost_pounds

    def get_total_with_shipping(self, obj):
        return obj.total_with_shipping

    def get_shipping_stripe_format(self, obj):
        return obj.shipping_stripe_format


class OrderListSerializer(serializers.ModelSerializer):
    checkout_session = CheckoutSessionSerializer()
    past_orders = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = '__all__'

    def get_past_orders(self, obj):
        email = obj.checkout_session.email or ''
        order_ids = self.context['view'].past_ids_map.get(email, [])
        # excluimos la orden actual por si acaso
        past_orders = [oid for oid in order_ids if oid != obj.order_id]
        return past_orders


class CustomerOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = [
            'order_id',
            'status',
            'created',
            'tracking_number',
            'shipping_order_id',
            'checkout_session', 
        ]

    checkout_session = serializers.SerializerMethodField()

    def get_checkout_session(self, obj):
        cs = obj.checkout_session
        return {
            'email': cs.email,
            'shipping_address': AddressSerializer(cs.shipping_address).data if cs.shipping_address else None,
            'billing_address': AddressSerializer(cs.billing_address).data if cs.billing_address else None,
            'cart': {
                'gift_message': cs.cart.gift_message,
                'shipping_date': cs.cart.shipping_date,
                'items': [
                    {
                        'product': item.product.name,
                        'quantity': item.quantity
                    }
                    for item in cs.cart.items.all()
                ]
            }
        }


class CustomerShippingDateUpdateSerializer(serializers.Serializer):
    shipping_date = serializers.DateField(required=True)

    def validate_shipping_date(self, value):
        from django.utils import timezone
        if value < timezone.now().date():
            raise serializers.ValidationError("Shipping date cannot be in the past")
        return value
