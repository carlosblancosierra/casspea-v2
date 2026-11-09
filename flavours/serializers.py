from rest_framework import serializers
from allergens.serializers import AllergenSerializer
from flavours.models import Flavour, FlavourCategory


class FlavourCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = FlavourCategory
        fields = '__all__'


class FlavourSerializer(serializers.ModelSerializer):
    allergens = AllergenSerializer(many=True)
    category = FlavourCategorySerializer()
    # From the category, so the shop can badge a flavour and keep it out of the
    # box builders without working the date out itself.
    coming_soon = serializers.BooleanField(source='is_coming_soon', read_only=True)
    available_from = serializers.DateField(source='category.available_from', read_only=True)

    class Meta:
        model = Flavour
        fields = '__all__'
