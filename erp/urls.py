"""
URL configuration for erp project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from products.urls import products_urls
from flavours.urls import flavours_urls
from carts.urls import carts_urls
from checkout.urls import urlpatterns as checkout_urls
from addresses.urls import urlpatterns as addresses_urls
from shipping.urls import urlpatterns as shipping_urls
from users.urls import urlpatterns as user_urls
from orders.urls import urlpatterns as orders_urls
from royalmail.urls import urlpatterns as royalmail_urls
from mails.urls import urlpatterns as mails_urls
from personalized.urls import urlpatterns as personalized_urls
from discounts.urls import urlpatterns as discounts_urls
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
from django.conf import settings
from django.conf.urls.static import static
from .views import health_check
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import JsonResponse

@ensure_csrf_cookie
def get_csrf_token(request):
    return JsonResponse({'detail': 'CSRF cookie set'})

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/products/', include(products_urls)),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    path('api/flavours/', include(flavours_urls)),
    path('api/carts/', include(carts_urls)),
    path('api/checkout/', include(checkout_urls)),
    path('api/addresses/', include(addresses_urls)),
    path('health/', health_check, name='health_check'),
    path('api/csrf/', get_csrf_token),
    path('api/shipping/', include(shipping_urls)),
    path('api/leads/', include('leads.urls')),
    path('api/users/', include(user_urls)),
    path('api/orders/', include(orders_urls)),
    path('api/royalmail/', include(royalmail_urls)),
    path('api/mails/', include(mails_urls)),
    path('api/personalized/', include(personalized_urls)),
    path('api/discounts/', include(discounts_urls)),
]

if settings.DEBUG and not settings.USE_S3:
    # Serve static and media files in development
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
