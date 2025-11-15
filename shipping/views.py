from rest_framework.viewsets import ReadOnlyModelViewSet
from .models import ShippingCompany

from .serializers import ShippingCompanyWithOptionsSerializer


class ShippingOptionsViewSet(ReadOnlyModelViewSet):
    serializer_class = ShippingCompanyWithOptionsSerializer

    def get_serializer_context(self):
        """Pass request to serializer context so it can access the cart"""
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        # Simplified - the free shipping logic is now handled in the serializer
        companies = ShippingCompany.objects.filter(
            active=True,
            options__active=True
        ).distinct()

        return companies
