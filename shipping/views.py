from django.shortcuts import render

from rest_framework.viewsets import ReadOnlyModelViewSet
from rest_framework.response import Response
from .models import ShippingOption, ShippingCompany
from carts.models import Cart

from .serializers import ShippingCompanyWithOptionsSerializer

import decimal


class ShippingOptionsViewSet(ReadOnlyModelViewSet):
    serializer_class = ShippingCompanyWithOptionsSerializer

    def get_queryset(self):
        cart, _ = Cart.objects.get_or_create_from_request(self.request)

        companies = ShippingCompany.objects.filter(
            active=True,
            options__active=True
        ).distinct()

        if cart.discounted_total >= 50:
            for company in companies:
                for option in company.options.filter(active=True):
                    if option.cents and option.cents <= 500:
                        option.price = decimal.Decimal('0')

        return companies
