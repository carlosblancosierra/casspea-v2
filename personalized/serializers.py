from rest_framework import serializers
from django.utils.text import slugify

from .models import (
    LayerColor,
    LayerType,
    ChocolateTemplate,
    TemplateLayerSlot,
    ChocolateLayer,
)


class LayerColorSerializer(serializers.ModelSerializer):
    class Meta:
        model = LayerColor
        fields = ['name', 'slug', 'hex_code']


class LayerTypeSerializer(serializers.ModelSerializer):
    colors = serializers.SerializerMethodField()

    class Meta:
        model = LayerType
        fields = ['name', 'colors']

    def get_colors(self, obj):
        """
        Generate color data dynamically, including slugs and image paths.
        """
        all_colors = LayerColor.objects.all()
        color_data = []
        for color in all_colors:
            layer_type_slug = slugify(obj.name)
            color_slug = color.slug

            top_image_path = f"/personalized/{layer_type_slug}/{color_slug}/top.png"
            side_image_path = f"/personalized/{layer_type_slug}/{color_slug}/side.png"

            color_data.append({
                "name": color.name,
                "slug": color.slug,
                "hex_code": color.hex_code,
                "top_image": top_image_path,
                "side_image": side_image_path,
            })
        return color_data


class TemplateLayerSlotSerializer(serializers.ModelSerializer):
    layer_type = LayerTypeSerializer()

    class Meta:
        model = TemplateLayerSlot
        fields = ['layer_type', 'name', 'order']


class ChocolateTemplateListSerializer(serializers.ModelSerializer):

    class Meta:
        model = ChocolateTemplate
        fields = ['title', 'slug']


class ChocolateTemplateDetailSerializer(serializers.ModelSerializer):
    layers = serializers.SerializerMethodField()

    class Meta:
        model = ChocolateTemplate
        fields = ['title', 'slug', 'layers']

    def get_layers(self, obj):
        slots = TemplateLayerSlot.objects.filter(template=obj).select_related(
            'layer_type',
        ).order_by('order')
        layers = TemplateLayerSlotSerializer(slots, many=True)
        return layers.data


class ChocolateLayerSerializer(serializers.ModelSerializer):
    layer_type = LayerTypeSerializer()
    color = LayerColorSerializer()

    class Meta:
        model = ChocolateLayer
        fields = ['layer_type', 'color', 'top_image', 'side_image']

class PersonalisedRequestSerializer(serializers.Serializer):
    """What the storefront's PersonalizedForm posts."""
    template_slug = serializers.SlugRelatedField(
        source='template', slug_field='slug', queryset=ChocolateTemplate.objects.all(),
    )
    email = serializers.EmailField()
    comments = serializers.CharField(required=False, allow_blank=True, max_length=2000, default='')
    custom_design_names = serializers.ListField(
        child=serializers.CharField(max_length=100, allow_blank=True), required=False, default=list, max_length=20,
    )
    flavours = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list, max_length=100,
    )
    quantity = serializers.IntegerField(min_value=1, max_value=100000)
