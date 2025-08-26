from rest_framework import status, viewsets, serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404
import logging

from .models import Cart, CartItem, Product
from .serializers import (
    CartSerializer,
    CartItemCreateSerializer,
    CartUpdateSerializer,
    CartItemQuantityUpdateSerializer,
)

logger = logging.getLogger(__name__)


class CartView(APIView):
    def get_cart(self, request):
        cart, _ = Cart.objects.get_or_create_from_request(request)
        return cart

    def get(self, request):
        """Get or create a session cart"""
        cart = self.get_cart(request)
        serializer = CartSerializer(cart)
        return Response(serializer.data)

    def post(self, request):
        """Update cart details"""
        cart = self.get_cart(request)

        data = request.data.copy()
        logger.debug(f"Update request data: {data}")

        if data.get('remove_discount'):
            cart.discount = None
            cart.save()
            data.pop('remove_discount', None)

        serializer = CartUpdateSerializer(cart, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        cart = serializer.save()
        return Response({
            "detail": "Cart updated successfully",
            "cart": CartSerializer(cart).data
        })


class CartItemViewSet(viewsets.ViewSet):
    """ /items/ endpoints """

    def get_cart(self, request):
        cart, _ = Cart.objects.get_or_create_from_request(request)
        return cart

    def _validate_product_and_qty(self, request):
        product_id = request.data.get('product')
        quantity = int(request.data.get('quantity', 1))
        try:
            product = Product.objects.get(pk=product_id)
        except Product.DoesNotExist:
            raise serializers.ValidationError({
                "product": "Product not found"
            })
        if quantity < 1:
            raise serializers.ValidationError({
                "quantity": "Quantity must be greater than 0"
            })
        return product, quantity

    def create(self, request):
        """POST /items/"""
        cart = self.get_cart(request)
        # Early validation for clearer errors
        self._validate_product_and_qty(request)

        serializer = CartItemCreateSerializer(data=request.data)
        logger.debug(
            f"CartItemView create payload: {request.data}"
        )

        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(cart=cart)
        except Exception as e:
            logger.exception("Error creating cart item")
            raise serializers.ValidationError({"detail": str(e)})

        cart.refresh_from_db()
        return Response(
            CartSerializer(cart).data,
            status=status.HTTP_201_CREATED
        )

    def update(self, request, pk=None):
        """PUT /items/{pk}/"""
        cart = self.get_cart(request)
        cart_item = get_object_or_404(CartItem, pk=pk, cart=cart)

        # Optional product/qty validation
        if 'product' in request.data or 'quantity' in request.data:
            if 'product' in request.data:
                try:
                    Product.objects.get(pk=request.data.get('product'))
                except Product.DoesNotExist:
                    raise serializers.ValidationError({
                        "product": "Product not found"
                    })
            if (
                'quantity' in request.data and
                int(request.data.get('quantity', 0)) < 1
            ):
                raise serializers.ValidationError({
                    "quantity": "Quantity must be greater than 0"
                })

        serializer = CartItemCreateSerializer(
            cart_item, data=request.data, partial=True
        )
        logger.debug(
            f"CartItemView update payload: {request.data}"
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        cart.refresh_from_db()
        return Response(
            CartSerializer(cart).data,
            status=status.HTTP_200_OK
        )

    def destroy(self, request, pk=None):
        """DELETE /items/{pk}/"""
        cart = self.get_cart(request)
        cart_item = get_object_or_404(CartItem, pk=pk, cart=cart)
        cart_item.delete()
        cart.refresh_from_db()
        return Response(
            CartSerializer(cart).data,
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['delete'], url_path='remove', url_name='remove')
    def remove(self, request, pk=None):
        """DELETE /items/{pk}/remove"""
        cart = self.get_cart(request)
        cart_item = get_object_or_404(CartItem, pk=pk, cart=cart)
        cart_item.delete()
        cart.refresh_from_db()
        return Response(
            CartSerializer(cart).data,
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['patch'], url_path='change-quantity', url_name='change_quantity')
    def change_quantity(self, request, pk=None):
        """PATCH /items/{pk}/change-quantity"""
        cart = self.get_cart(request)
        cart_item = get_object_or_404(CartItem, pk=pk, cart=cart)
        serializer = CartItemQuantityUpdateSerializer(
            cart_item, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        cart.refresh_from_db()
        return Response(
            CartSerializer(cart).data,
            status=status.HTTP_200_OK
        )
