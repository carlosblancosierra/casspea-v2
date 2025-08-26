from rest_framework import serializers
from django.utils import timezone

from flavours.models import Flavour
from flavours.serializers import FlavourSerializer
from allergens.models import Allergen
from allergens.serializers import AllergenSerializer

from .models import (
    Cart,
    CartItem,
    CartItemBoxCustomization,
    CartItemBoxFlavorSelection,
    CartItemPackCustomization,
)
from products.models import Product
from products.serializers import ProductSerializer
from discounts.serializers import DiscountSerializer
from discounts.models import Discount


# -------- READ SERIALIZERS --------

class CartItemBoxFlavorSelectionSerializer(serializers.ModelSerializer):
    flavor = FlavourSerializer()

    class Meta:
        model = CartItemBoxFlavorSelection
        fields = ['id', 'flavor', 'quantity']


class CartItemBoxCustomizationSerializer(serializers.ModelSerializer):
    allergens = AllergenSerializer(many=True)
    flavor_selections = CartItemBoxFlavorSelectionSerializer(many=True)

    class Meta:
        model = CartItemBoxCustomization
        fields = ['id', 'selection_type', 'allergens', 'flavor_selections']


class CartItemPackCustomizationSerializer(serializers.ModelSerializer):
    allergens = AllergenSerializer(many=True)
    # IMPORTANT: match the related_name on the model FK from CartItemBoxFlavorSelection -> CartItemPackCustomization
    flavor_selections = CartItemBoxFlavorSelectionSerializer(source="flavor_selections_pack", many=True)

    class Meta:
        model = CartItemPackCustomization
        fields = [
            'id',
            'selection_type',
            'allergens',
            'flavor_selections',
            'hot_chocolate',
            'gift_card',
            'chocolate_bark',
        ]


class CartItemSerializer(serializers.ModelSerializer):
    product = ProductSerializer()
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
    discount = DiscountSerializer(read_only=True)
    gift_message = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    shipping_date = serializers.DateField(required=False, allow_null=True)
    base_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    discounted_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    total_savings = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    is_discount_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = Cart
        fields = [
            'id',
            'items',
            'discount',
            'gift_message',
            'shipping_date',
            'base_total',
            'discounted_total',
            'total_savings',
            'is_discount_valid',
            'created',
            'updated'
        ]

    def validate(self, data):
        if self.instance and self.instance.discount:
            if not self.instance.is_discount_valid:
                raise serializers.ValidationError({
                    "discount": f"Order total must be at least £{self.instance.discount.min_order_value} to use this discount code"
                })
        return data

    def validate_shipping_date(self, value):
        if value and value < timezone.now().date():
            raise serializers.ValidationError("Shipping date cannot be in the past")
        return value


# -------- WRITE SERIALIZERS --------

class CartItemBoxFlavorSelectionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CartItemBoxFlavorSelection
        fields = ['flavor', 'quantity']


class CartItemBoxCustomizationCreateSerializer(serializers.ModelSerializer):
    flavor_selections = CartItemBoxFlavorSelectionCreateSerializer(many=True, required=False)
    allergens = serializers.PrimaryKeyRelatedField(many=True, queryset=Allergen.objects.all(), required=False)

    class Meta:
        model = CartItemBoxCustomization
        fields = ['selection_type', 'allergens', 'flavor_selections']


class CartItemPackCustomizationCreateSerializer(serializers.ModelSerializer):
    # IMPORTANT: use the same source ("flavor_selections_pack") that matches the model related_name
    flavor_selections = CartItemBoxFlavorSelectionCreateSerializer(
        source="flavor_selections_pack", many=True, required=False
    )
    allergens = serializers.PrimaryKeyRelatedField(many=True, queryset=Allergen.objects.all(), required=False)

    class Meta:
        model = CartItemPackCustomization
        fields = ['selection_type', 'allergens', 'flavor_selections', 'hot_chocolate', 'gift_card', 'chocolate_bark']


class CartItemCreateSerializer(serializers.ModelSerializer):
    box_customization = CartItemBoxCustomizationCreateSerializer(required=False)
    pack_customization = CartItemPackCustomizationCreateSerializer(required=False)
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())

    class Meta:
        model = CartItem
        fields = ['product', 'quantity', 'box_customization', 'pack_customization']

    def validate(self, data):
        product = data['product']
        box_customization = data.get('box_customization')
        pack_customization = data.get('pack_customization')

        if box_customization and pack_customization:
            raise serializers.ValidationError("Cannot provide both box_customization and pack_customization.")

        if box_customization:
            if box_customization.get('selection_type') == 'PICK_AND_MIX':
                flavor_selections = box_customization.get('flavor_selections', [])
                total_quantity = sum(fs['quantity'] for fs in flavor_selections)
                if total_quantity != product.units_per_box:
                    raise serializers.ValidationError({
                        'box_customization': {
                            'flavor_selections': f"Total flavor quantity must equal {product.units_per_box} (got {total_quantity})"
                        }
                    })
            elif box_customization.get('selection_type') == 'RANDOM':
                if box_customization.get('flavor_selections'):
                    raise serializers.ValidationError({
                        'box_customization': {
                            'flavor_selections': "Flavor selections should not be provided for RANDOM selection type"
                        }
                    })

        # If you have specific choices for pack selection_type, optionally validate here.

        return data

    # CREATE with consistent related names
    def create(self, validated_data):
        box_customization_data = validated_data.pop('box_customization', None)
        pack_customization_data = validated_data.pop('pack_customization', None)

        if box_customization_data and pack_customization_data:
            raise serializers.ValidationError("Cannot provide both box_customization and pack_customization.")

        cart = self.context.get('cart')  # not strictly needed; kept for future
        cart_item = CartItem.objects.create(**validated_data)

        if box_customization_data:
            flavor_selections_data = box_customization_data.pop('flavor_selections', [])
            allergens_data = box_customization_data.pop('allergens', [])
            box_customization = CartItemBoxCustomization.objects.create(cart_item=cart_item, **box_customization_data)
            if allergens_data:
                box_customization.allergens.set(allergens_data)
            for flavor_data in flavor_selections_data:
                CartItemBoxFlavorSelection.objects.create(box_customization=box_customization, **flavor_data)

        if pack_customization_data:
            # NOTE: flavor selections come in under source="flavor_selections_pack"
            flavor_selections_data = pack_customization_data.pop('flavor_selections_pack', [])
            allergens_data = pack_customization_data.pop('allergens', [])
            pack_customization = CartItemPackCustomization.objects.create(
                cart_item=cart_item, **pack_customization_data)
            if allergens_data:
                pack_customization.allergens.set(allergens_data)
            for flavor_data in flavor_selections_data:
                CartItemBoxFlavorSelection.objects.create(pack_customization=pack_customization, **flavor_data)

        return cart_item

    # UPDATE with consistent related names
    def update(self, instance, validated_data):
        box_customization_data = validated_data.pop('box_customization', None)
        pack_customization_data = validated_data.pop('pack_customization', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if box_customization_data is not None:
            box_customization = getattr(instance, 'box_customization', None)
            if box_customization is None:
                box_customization = CartItemBoxCustomization.objects.create(cart_item=instance)

            flavor_selections_data = box_customization_data.pop('flavor_selections', None)
            for attr, value in box_customization_data.items():
                if attr == 'allergens':
                    box_customization.allergens.set(value)
                else:
                    setattr(box_customization, attr, value)
            box_customization.save()

            if flavor_selections_data is not None:
                box_customization.flavor_selections.all().delete()
                for flavor_data in flavor_selections_data:
                    CartItemBoxFlavorSelection.objects.create(box_customization=box_customization, **flavor_data)

        if pack_customization_data is not None:
            pack_customization = getattr(instance, 'pack_customization', None)
            if pack_customization is None:
                # When creating via update, keep base fields; flavor selections come after
                base_fields = {k: v for k, v in pack_customization_data.items() if k not in (
                    'flavor_selections', 'flavor_selections_pack', 'allergens')}
                pack_customization = CartItemPackCustomization.objects.create(cart_item=instance, **base_fields)

            # Serializer used source="flavor_selections_pack"
            flavor_selections_data = (
                pack_customization_data.pop('flavor_selections_pack', None) or
                pack_customization_data.pop('flavor_selections', None)
            )

            for attr, value in pack_customization_data.items():
                if attr == 'allergens':
                    pack_customization.allergens.set(value)
                else:
                    setattr(pack_customization, attr, value)
            pack_customization.save()

            if flavor_selections_data is not None:
                # IMPORTANT: use the related_name matching the model
                pack_customization.flavor_selections_pack.all().delete()
                for flavor_data in flavor_selections_data:
                    CartItemBoxFlavorSelection.objects.create(pack_customization=pack_customization, **flavor_data)

        return instance


class CartUpdateSerializer(serializers.ModelSerializer):
    gift_message = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    shipping_date = serializers.DateField(required=False, allow_null=True)
    discount_code = serializers.CharField(required=False, allow_null=True, allow_blank=True, write_only=True)
    remove_discount = serializers.BooleanField(required=False, write_only=True)

    class Meta:
        model = Cart
        fields = ['gift_message', 'shipping_date', 'discount_code', 'remove_discount']

    def validate_shipping_date(self, value):
        if value and value < timezone.now().date():
            raise serializers.ValidationError("Shipping date cannot be in the past")
        return value

    def update(self, instance, validated_data):
        discount_code = validated_data.pop('discount_code', None)
        _ = validated_data.pop('remove_discount', None)  # handled in view

        if discount_code is not None:
            if discount_code == '':
                instance.discount = None
            else:
                try:
                    discount = Discount.objects.get(code__iexact=discount_code)
                    if not discount.status[0]:
                        raise serializers.ValidationError({"discount_code": discount.status[1]})
                    instance.discount = discount
                except Discount.DoesNotExist:
                    raise serializers.ValidationError({"discount_code": "Invalid discount code provided."})

        return super().update(instance, validated_data)


class CartItemQuantityUpdateSerializer(serializers.ModelSerializer):
    quantity = serializers.IntegerField(min_value=1)

    class Meta:
        model = CartItem
        fields = ['quantity']
