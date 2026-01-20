from rest_framework import serializers
from .models import Product, ProductCategory, ProductGalleryImage


class ProductCategoryShallowSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = ['id', 'name', 'slug']  # Only the essentials


class ProductCategorySerializer(serializers.ModelSerializer):
    products = serializers.SerializerMethodField()

    def get_products(self, obj):
        products = Product.objects.filter(category=obj, active=True)
        return ProductSerializer(products, many=True).data

    class Meta:
        model = ProductCategory
        fields = '__all__'


class ProductGalleryImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductGalleryImage
        fields = [
            'id',
            'image',
            'image_webp',
            'thumbnail',
            'thumbnail_webp',
            'alt_text',
            'order'
        ]


class ProductSerializer(serializers.ModelSerializer):
    current_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    category = ProductCategoryShallowSerializer()
    gallery_images = ProductGalleryImageSerializer(many=True, read_only=True)
    is_preorder_active = serializers.BooleanField(read_only=True)
    is_pickup_available = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = [
            'id',
            'name',
            'description',
            'category',
            'base_price',
            'stripe_price_id',
            'slug',
            'weight',
            'active',
            'sold_out',
            'units_per_box',
            'main_color',
            'secondary_color',
            'seo_title',
            'seo_description',
            'image',
            'image_webp',
            'thumbnail',
            'thumbnail_webp',
            'gallery_images',
            'preorder',
            'preorder_price',
            'preorder_finish_date',
            'is_preorder_active',
            'current_price',
            'pickup_only',
            'pickup_from_date',
            'alert_message',
            'is_pickup_available',
            'can_pick_allergens',
            'created',
            'updated'
        ]
