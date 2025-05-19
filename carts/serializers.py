from rest_framework import serializers
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
from django.utils import timezone
from discounts.models import Discount

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
    flavor_selections = CartItemBoxFlavorSelectionSerializer(many=True)
    
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
        """Validate the cart data"""
        if self.instance and self.instance.discount:
            if not self.instance.is_discount_valid:
                raise serializers.ValidationError({
                    "discount": f"Order total must be at least £{self.instance.discount.min_order_value} to use this discount code"
                })
        return data

    def validate_shipping_date(self, value):
        """
        Validate shipping date is not in the past
        """
        if value and value < timezone.now().date():
            raise serializers.ValidationError("Shipping date cannot be in the past")
        return value

    def get_total(self, obj):
        return str(sum(item.quantity * item.product.base_price for item in obj.items.all()))


# Write serializers (for POST/PUT requests)
class CartItemBoxFlavorSelectionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CartItemBoxFlavorSelection
        fields = ['flavor', 'quantity']

class CartItemBoxCustomizationCreateSerializer(serializers.ModelSerializer):
    flavor_selections = CartItemBoxFlavorSelectionCreateSerializer(many=True, required=False)
    allergens = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Allergen.objects.all(),
        required=False
    )

    class Meta:
        model = CartItemBoxCustomization
        fields = ['selection_type', 'allergens', 'flavor_selections']

class CartItemPackCustomizationCreateSerializer(serializers.ModelSerializer):
    flavor_selections = CartItemBoxFlavorSelectionCreateSerializer(many=True, required=False)
    allergens = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Allergen.objects.all(),
        required=False
    )

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
        """Validate the complete data set"""
        product = data['product']
        box_customization = data.get('box_customization', None)
        pack_customization = data.get('pack_customization', None)

        if box_customization and pack_customization:
            raise serializers.ValidationError("Cannot provide both box_customization and pack_customization.")

        if box_customization:
            # Only validate flavor selections for PICK_AND_MIX
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
                # For RANDOM selection, flavor_selections should be empty or None
                if box_customization.get('flavor_selections'):
                    raise serializers.ValidationError({
                        'box_customization': {
                            'flavor_selections': "Flavor selections should not be provided for RANDOM selection type"
                        }
                    })

        return data

    def create(self, validated_data):
        box_customization_data = validated_data.pop('box_customization', None)
        pack_customization_data = validated_data.pop('pack_customization', None)

        if box_customization_data and pack_customization_data:
            raise serializers.ValidationError("Cannot provide both box_customization and pack_customization.")

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
            flavor_selections_data = pack_customization_data.pop('flavor_selections', [])
            allergens_data = pack_customization_data.pop('allergens', [])
            pack_customization = CartItemPackCustomization.objects.create(cart_item=cart_item, **pack_customization_data)
            if allergens_data:
                pack_customization.allergens.set(allergens_data)
            for flavor_data in flavor_selections_data:
                CartItemBoxFlavorSelection.objects.create(pack_customization=pack_customization, **flavor_data)

        return cart_item

    def update(self, instance, validated_data):
        box_customization_data = validated_data.pop('box_customization', None)
        pack_customization_data = validated_data.pop('pack_customization', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if box_customization_data:
            box_customization = instance.box_customization
            flavor_selections_data = box_customization_data.pop('flavor_selections', None)

            for attr, value in box_customization_data.items():
                if attr == 'allergens':
                    box_customization.allergens.set(value)
                else:
                    setattr(box_customization, attr, value)
            box_customization.save()

            if flavor_selections_data:
                box_customization.flavor_selections.all().delete()
                for flavor_data in flavor_selections_data:
                    CartItemBoxFlavorSelection.objects.create(box_customization=box_customization, **flavor_data)

        if pack_customization_data:
            try:
                pack_customization = instance.pack_customization
            except CartItemPackCustomization.DoesNotExist:
                pack_customization = CartItemPackCustomization.objects.create(cart_item=instance, **pack_customization_data)
            else:
                flavor_selections_data = pack_customization_data.pop('flavor_selections', None)
                for attr, value in pack_customization_data.items():
                    if attr == 'allergens':
                        pack_customization.allergens.set(value)
                    else:
                        setattr(pack_customization, attr, value)
                pack_customization.save()
                if flavor_selections_data:
                    pack_customization.flavor_selections.all().delete()
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
        fields = [
            'gift_message',
            'shipping_date',
            'discount_code',
            'remove_discount'
        ]

    def validate_shipping_date(self, value):
        if value and value < timezone.now().date():
            raise serializers.ValidationError("Shipping date cannot be in the past")
        return value

    def update(self, instance, validated_data):
        discount_code = validated_data.pop('discount_code', None)
        remove_discount = validated_data.pop('remove_discount', None)
        try:
            if discount_code is not None:
                if discount_code == '':
                    instance.discount = None
                else:  # Try to apply new discount
                    discount = Discount.objects.get(code__iexact=discount_code)
                    if not discount.status[0]:
                        raise serializers.ValidationError({"discount_code": discount.status[1]})
                    instance.discount = discount
        except Discount.DoesNotExist:
            raise serializers.ValidationError({"discount_code": "Invalid discount code provided."})
        except serializers.ValidationError as e:
            raise e
        except Exception as e:
            raise serializers.ValidationError({"discount_code": f"An unexpected error occurred: {str(e)}"})

        return super().update(instance, validated_data)

class CartItemQuantityUpdateSerializer(serializers.ModelSerializer):
    quantity = serializers.IntegerField(min_value=1)

    class Meta:
        model = CartItem
        fields = ['quantity']
