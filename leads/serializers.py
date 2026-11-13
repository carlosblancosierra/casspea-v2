from rest_framework import serializers
from .models import Lead
from .unsubscribe import is_opted_out


class LeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        fields = '__all__'
        # Whether someone opted out is decided by the unsubscribe link, never
        # by the form that sends the lead.
        read_only_fields = ['unsubscribed']

    def create(self, validated_data):
        # Someone who used an unsubscribe link and later enters a giveaway or
        # landing page is still opted out. A new lead used to start with
        # unsubscribed=False, so the admin list and CSV export (what the
        # newsletter is sent from) showed them as subscribed again.
        validated_data['unsubscribed'] = is_opted_out(validated_data.get('email'))
        return super().create(validated_data)
