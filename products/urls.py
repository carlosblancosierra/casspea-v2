from django.urls import path
from .views import ProductListView, ProductDetailView, ProductCategoryListView, ProductCategoryDetailView

products_urls = [
    path('', ProductListView.as_view(), name='product-list'),
    path('categories/', ProductCategoryListView.as_view(), name='product-category-list'),
    path('categories/<slug:slug>/', ProductCategoryDetailView.as_view(), name='product-category-detail'),
    path('<slug:slug>/', ProductDetailView.as_view(), name='product-detail'),
]
