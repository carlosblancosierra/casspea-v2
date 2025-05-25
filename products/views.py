from rest_framework.generics import ListAPIView, RetrieveAPIView
from .models import Product, ProductCategory
from .serializers import ProductSerializer, ProductCategorySerializer
import structlog

logger = structlog.get_logger(__name__)


class ProductListView(ListAPIView):
    queryset = Product.objects.active()
    serializer_class = ProductSerializer


class ProductDetailView(RetrieveAPIView):
    lookup_field = 'slug'
    queryset = Product.objects.active()
    serializer_class = ProductSerializer


class ProductCategoryListView(ListAPIView):
    queryset = ProductCategory.objects.all()
    serializer_class = ProductCategorySerializer

    def get(self, request, *args, **kwargs):
        logger.info("ProductCategoryListView called", path=request.path, user=str(request.user))
        return super().get(request, *args, **kwargs)


class ProductCategoryDetailView(RetrieveAPIView):
    lookup_field = 'slug'
    queryset = ProductCategory.objects.all()
    serializer_class = ProductCategorySerializer
