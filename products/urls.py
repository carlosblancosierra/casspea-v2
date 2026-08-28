from django.urls import path
from .views import ProductListView, ProductDetailView, ProductCategoryListView, ProductCategoryDetailView
from .admin_views import SummerBreakBoxesAdminView

products_urls = [
    path('', ProductListView.as_view(), name='product-list'),
    path('admin/summer-break-boxes/', SummerBreakBoxesAdminView.as_view(), name='summer-break-admin'),
    path('categories/', ProductCategoryListView.as_view(), name='product-category-list'),
    path('categories/<slug:slug>/', ProductCategoryDetailView.as_view(), name='product-category-detail'),
    path('<slug:slug>/', ProductDetailView.as_view(), name='product-detail'),
]
