from django.urls import path

from .views import mcp_endpoint

urlpatterns = [
    path('', mcp_endpoint, name='orders-mcp'),
    path('<str:path_token>/', mcp_endpoint, name='orders-mcp-token'),
]
