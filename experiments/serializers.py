from rest_framework import serializers

from .models import Event


class AssignRequestSerializer(serializers.Serializer):
    experiment = serializers.SlugField(max_length=64)


class EventRequestSerializer(serializers.Serializer):
    experiment = serializers.SlugField(max_length=64)
    name = serializers.CharField(max_length=64)

    def validate_name(self, value):
        # An open-ended event name would let anyone fill the table with junk
        # that no report reads.
        allowed = {Event.ADD_TO_CART}
        if value not in allowed:
            raise serializers.ValidationError(f'Unknown event name. Expected one of: {sorted(allowed)}')
        return value


class VariantResponseSerializer(serializers.Serializer):
    variant = serializers.CharField()
