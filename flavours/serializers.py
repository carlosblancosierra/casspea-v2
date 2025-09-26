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

    class Meta:
        model = Flavour
        fields = '__all__'
